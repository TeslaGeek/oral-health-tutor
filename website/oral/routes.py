import os
import hashlib
import hmac
import json
from datetime import datetime

from flask import Blueprint, redirect, render_template, request, url_for, jsonify, session as flask_session, current_app, Response
from openai import OpenAI
from sqlalchemy.orm.attributes import flag_modified

from .ai_feedback import (
    generate_feedback_for_session,
    generate_feedback_for_session_phase,
    looks_like_radiograph_template,
    _has_any_radiograph_findings,
)
from .case_loader import load_case
from .patient_chat import patient_chat_reply
from .db import SessionLocal
from .models import Case, Session, SessionStatus
from .utils_tests import build_test_results

oral_bp = Blueprint("oral", __name__)
tts_client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
DEFAULT_TTS_MODEL = os.getenv("ORAL_TTS_MODEL", "gpt-4o-mini-tts")
DEFAULT_TTS_VOICE = os.getenv("ORAL_TTS_VOICE", "marin")
DEFAULT_TTS_FORMAT = os.getenv("ORAL_TTS_FORMAT", "mp3")
DEFAULT_TTS_INSTRUCTIONS = os.getenv(
    "ORAL_TTS_INSTRUCTIONS",
    "Scottish female dental patient. Natural Scottish accent only.",
)


def phase1_hash(sess: Session) -> str:
    payload = {
        "hpc_notes": (sess.hpc_notes or "").strip(),
        "medical_history_notes": (sess.medical_history_notes or "").strip(),
        "expectations_notes": (sess.expectations_notes or "").strip(),
        "social_history_notes": (sess.social_history_notes or "").strip(),
        "diet_notes": (sess.diet_notes or "").strip(),
        "preventive_regime_notes": (sess.preventive_regime_notes or "").strip(),
    }
    canonical = json.dumps(payload, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def phase1_weight(attempt: int) -> float:
    if attempt <= 2:
        return 1.0
    if attempt == 3:
        return 0.8
    if attempt == 4:
        return 0.6
    return 0.5


def _iter_tts_audio_bytes(text: str, *, model: str, voice: str, instructions: str | None = None):
    with tts_client.audio.speech.with_streaming_response.create(
        model=model,
        voice=voice,
        input=text,
        instructions=instructions or DEFAULT_TTS_INSTRUCTIONS,
        response_format=DEFAULT_TTS_FORMAT,
    ) as response:
        for chunk in response.iter_bytes():
            yield chunk


def _admin_auth_response():
    username = os.getenv("ORAL_ADMIN_USERNAME")
    password = os.getenv("ORAL_ADMIN_PASSWORD")

    # Keep the endpoint unavailable unless production credentials are configured.
    if not username or not password:
        return Response("Not found", status=404, headers={"Cache-Control": "no-store"})

    auth = request.authorization
    username_matches = bool(auth) and hmac.compare_digest(auth.username or "", username)
    password_matches = bool(auth) and hmac.compare_digest(auth.password or "", password)
    if username_matches and password_matches:
        return None

    return Response(
        "Authentication required",
        status=401,
        headers={
            "WWW-Authenticate": 'Basic realm="Oral Health Tutor Admin", charset="UTF-8"',
            "Cache-Control": "no-store",
        },
    )


@oral_bp.route("/")
def welcome():
    return render_template("oral/welcome.html")


@oral_bp.route("/privacy")
def privacy():
    return render_template("oral/privacy.html")


@oral_bp.route("/cases")
def list_cases():
    db = SessionLocal()
    try:
        cases = db.query(Case).filter(Case.is_active == 1).all()
        case_payloads = {}
        for c in cases:
            try:
                case_payloads[c.id] = load_case(c.case_code)
            except FileNotFoundError:
                case_payloads[c.id] = None
    finally:
        db.close()
    return render_template("oral/case_list.html", cases=cases, case_payloads=case_payloads)


@oral_bp.route("/admin/sessions")
def admin_sessions():
    auth_response = _admin_auth_response()
    if auth_response is not None:
        return auth_response

    db = SessionLocal()
    try:
        sessions = (
            db.query(Session)
            .order_by(Session.id.desc())
            .limit(200)
            .all()
        )
        cases = {c.id: c for c in db.query(Case).all()}
        case_payloads = {}
        for case in cases.values():
            try:
                case_payloads[case.id] = load_case(case.case_code)
            except FileNotFoundError:
                case_payloads[case.id] = None
    finally:
        db.close()
    return Response(
        render_template(
            "oral/admin_sessions.html",
            sessions=sessions,
            cases=cases,
            case_payloads=case_payloads,
        ),
        headers={"Cache-Control": "no-store"},
    )


@oral_bp.route("/cases/<int:case_id>/start")
def start_case(case_id: int):
    db = SessionLocal()
    try:
        new_session = Session(
            student_identifier="student123",
            case_id=case_id,
            started_at=datetime.utcnow(),
            status=SessionStatus.IN_PROGRESS,
        )
        db.add(new_session)
        db.commit()
        session_id = new_session.id
    finally:
        db.close()
    return redirect(url_for("oral.phase1", session_id=session_id))


@oral_bp.route("/session/<int:session_id>/phase1", methods=["GET", "POST"])
def phase1(session_id: int):
    db = SessionLocal()
    try:
        sess = db.query(Session).get(session_id)
        if not sess:
            return "Session not found", 404
        case = db.query(Case).get(sess.case_id) if sess else None
        case_payload = None
        if case:
            try:
                case_payload = load_case(case.case_code)
            except FileNotFoundError:
                case_payload = None
        if request.method == "POST":
            save_only = (
                request.headers.get("X-Requested-With") == "XMLHttpRequest"
                or request.form.get("save_only") == "1"
            )
            def set_if_present(attr, field):
                if field in request.form:
                    setattr(sess, attr, (request.form.get(field) or "").strip())

            phase1_fields = (
                "hpc_notes",
                "medical_history_notes",
                "expectations_notes",
                "social_history_notes",
                "diet_notes",
                "preventive_regime_notes",
            )
            for field in phase1_fields:
                set_if_present(field, field)
            if any(field in request.form for field in phase1_fields):
                feedback_json = dict(sess.feedback_json or {})
                scores_json = dict(sess.section_scores_json or {})
                changed = False
                if "phase1_feedback" in feedback_json:
                    feedback_json.pop("phase1_feedback", None)
                    feedback_json.pop("phase1_feedback__hash", None)
                    changed = True
                if "phase1_scores" in scores_json:
                    scores_json.pop("phase1_scores", None)
                    changed = True
                if changed:
                    sess.feedback_json = feedback_json
                    sess.section_scores_json = scores_json
                    flag_modified(sess, "feedback_json")
                    flag_modified(sess, "section_scores_json")
            if not save_only and not sess.phase1_completed_at:
                sess.phase1_completed_at = datetime.utcnow()
            db.commit()
            db.refresh(sess)
            current_app.logger.info(
                "PHASE1 SAVED hpc=%r mh=%r exp=%r soc=%r diet=%r prev=%r",
                sess.hpc_notes,
                sess.medical_history_notes,
                sess.expectations_notes,
                sess.social_history_notes,
                sess.diet_notes,
                sess.preventive_regime_notes,
            )
            if save_only:
                return jsonify({"ok": True})
            return redirect(url_for("oral.phase2", session_id=session_id))
        chat_log = sess.chat_log or []
        return render_template(
            "oral/phase1.html",
            session_id=session_id,
            session=sess,
            case=case,
            case_payload=case_payload,
            chat_log=chat_log,
            current_phase=1,
        )
    finally:
        db.close()


@oral_bp.route("/session/<int:session_id>/phase2", methods=["GET", "POST"])
def phase2(session_id: int):
    db = SessionLocal()
    try:
        sess = db.query(Session).get(session_id)
        if not sess:
            return "Session not found", 404
        case = db.query(Case).get(sess.case_id) if sess else None
        case_payload = None
        test_options = []
        test_results = []
        if case:
            try:
                case_payload = load_case(case.case_code)
                test_options, test_results = build_test_results(case_payload, sess.selected_tests, audience="student")
            except FileNotFoundError:
                case_payload = None
        if request.method == "POST":
            save_only = (
                request.headers.get("X-Requested-With") == "XMLHttpRequest"
                or request.form.get("save_only") == "1"
            )
            def set_if_present(attr, field):
                if field in request.form:
                    setattr(sess, attr, (request.form.get(field) or "").strip())

            if "selected_tests" in request.form:
                if not getattr(sess, "phase2_investigations_locked", False):
                    sess.selected_tests = request.form.getlist("selected_tests")
            set_if_present("test_justification", "test_justification")
            set_if_present("radiograph_report", "radiograph_report")
            set_if_present("investigation_notes", "investigation_notes")
            set_if_present("diagnoses", "diagnoses")
            set_if_present("risk_assessment", "risk_assessment")
            if not save_only and not sess.phase2_completed_at:
                sess.phase2_completed_at = datetime.utcnow()
            action = request.form.get("action", "continue")
            db.commit()
            if save_only:
                return jsonify({"ok": True})
            if action == "save":
                return redirect(url_for("oral.phase2", session_id=session_id))
            # --- Phase 2 "warn but allow override" gate -------------------------
            proceed_anyway = request.form.get("phase2_proceed_anyway") == "1"

            selected = sess.selected_tests or []
            rr = (sess.radiograph_report or "").strip()
            inv = (sess.investigation_notes or "").strip()

            # Warn scenarios (Phase 2A incomplete)
            no_interpretation = bool(selected) and not (rr or inv)

            # Warn scenario (radiograph looks like template headings)
            template_rad = bool(rr) and looks_like_radiograph_template(rr) and not _has_any_radiograph_findings(rr)

            should_warn = (action == "continue") and (no_interpretation or template_rad) and not proceed_anyway

            if should_warn:
                # Rebuild test results (same as GET) so the page renders correctly
                case_payload = None
                test_options, test_results = [], []
                if case:
                    try:
                        case_payload = load_case(case.case_code)
                        test_options, test_results = build_test_results(
                            case_payload,
                            sess.selected_tests,
                            audience="student",
                        )
                    except FileNotFoundError:
                        case_payload = None

                msg = (
                    "You selected investigations but haven’t documented any interpretation yet. "
                    "Marks in this phase come from your written findings in the radiograph report and/or "
                    "investigation notes."
                    if no_interpretation else
                    "Your radiograph text looks like a reporting template rather than observed findings. "
                    "Write what you actually saw (quality A/U, tooth + surface + depth/extent, bone levels, calculus)."
                )

                return render_template(
                    "oral/phase2.html",
                    session_id=session_id,
                    session=sess,
                    case=case,
                    case_payload=case_payload,
                    test_options=test_options,
                    test_results=test_results,
                    chat_log=sess.chat_log or [],
                    current_phase=2,
                    phase2_continue_warning=True,
                    phase2_continue_warning_msg=msg,
                )
            # --- end gate -------------------------------------------------------
            return redirect(url_for("oral.phase3", session_id=session_id))
        chat_log = sess.chat_log or []
        return render_template(
            "oral/phase2.html",
            session_id=session_id,
            session=sess,
            case=case,
            case_payload=case_payload,
            test_options=test_options,
            test_results=test_results,
            chat_log=chat_log,
            current_phase=2,
        )
    finally:
        db.close()


@oral_bp.route("/session/<int:session_id>/phase3", methods=["GET", "POST"])
def phase3(session_id: int):
    db = SessionLocal()
    try:
        sess = db.query(Session).get(session_id)
        if not sess:
            return "Session not found", 404
        case = db.query(Case).get(sess.case_id) if sess else None
        case_payload = None
        test_results = []
        test_options = []
        if case:
            try:
                case_payload = load_case(case.case_code)
                test_options, test_results = build_test_results(case_payload, sess.selected_tests, audience="student")
            except FileNotFoundError:
                case_payload = None
        if request.method == "POST":
            save_only = (
                request.headers.get("X-Requested-With") == "XMLHttpRequest"
                or request.form.get("save_only") == "1"
            )
            def set_if_present(attr, field):
                if field in request.form:
                    setattr(sess, attr, (request.form.get(field) or "").strip())

            set_if_present("prevention_plan", "prevention_plan")
            set_if_present("rehab_options", "rehab_options")
            set_if_present("operative_options", "operative_options")
            set_if_present("patient_preferences", "patient_preferences")
            set_if_present("final_plan_and_consent_notes", "final_plan_and_consent_notes")

            if not save_only:
                if not sess.phase3_completed_at:
                    sess.phase3_completed_at = datetime.utcnow()
                sess.completed_at = datetime.utcnow()
                sess.status = SessionStatus.SUBMITTED
            db.commit()
            if save_only:
                return jsonify({"ok": True})

            # Generate feedback synchronously unless disabled
            if os.getenv("DISABLE_AI_FEEDBACK") == "1":
                db.commit()
                return redirect(url_for("oral.completed", session_id=session_id))

            try:
                feedback, scores, overall = generate_feedback_for_session(sess, case_payload=case_payload)
                sess.feedback_json = feedback
                sess.section_scores_json = scores
                if overall is not None:
                    sess.overall_score = overall
                sess.status = SessionStatus.MARKED
            except Exception:
                current_app.logger.exception("Error generating AI feedback during Phase 3 submit")
                sess.status = SessionStatus.SUBMITTED

            db.commit()
            return redirect(url_for("oral.completed", session_id=session_id))
        chat_log = sess.chat_log or []
        return render_template(
            "oral/phase3.html",
            session_id=session_id,
            session=sess,
            case=case,
            case_payload=case_payload,
            test_results=test_results,
            test_options=test_options,
            chat_log=chat_log,
            current_phase=3,
        )
    finally:
        db.close()


@oral_bp.route("/session/<int:session_id>/completed")
def completed(session_id: int):
    db = SessionLocal()
    try:
        sess = db.query(Session).get(session_id)
        if not sess:
            return "Session not found", 404
        case = db.query(Case).get(sess.case_id) if sess else None
        case_payload = None
        if case:
            try:
                case_payload = load_case(case.case_code)
            except FileNotFoundError:
                case_payload = None
    finally:
        db.close()
    return render_template(
        "oral/completed.html",
        session=sess,
        case=case,
        case_payload=case_payload,
    )


@oral_bp.route("/session/<int:session_id>/generate-feedback", methods=["POST"])
def generate_feedback(session_id: int):
    db = SessionLocal()
    try:
        sess = db.query(Session).get(session_id)
        if not sess:
            return jsonify({"ok": False, "error": "Session not found"}), 404
        case = db.query(Case).get(sess.case_id) if sess else None
        case_payload = None
        if case:
            try:
                case_payload = load_case(case.case_code)
            except FileNotFoundError:
                case_payload = None

        if os.getenv("DISABLE_AI_FEEDBACK") == "1":
            return jsonify({"ok": False, "error": "AI feedback disabled"}), 503

        # If already marked with feedback, return it
        if sess.status == SessionStatus.MARKED and sess.feedback_json:
            html = render_template("oral/_feedback_block.html", session=sess)
            return jsonify({"ok": True, "status": "marked", "feedback_html": html}), 200

        # Generate synchronously
        try:
            feedback, scores, overall = generate_feedback_for_session(sess, case_payload=case_payload)
            sess.feedback_json = feedback
            sess.section_scores_json = scores
            if overall is not None:
                sess.overall_score = overall
            sess.status = SessionStatus.MARKED
            db.commit()

            html = render_template("oral/_feedback_block.html", session=sess)
            return jsonify({"ok": True, "status": "marked", "feedback_html": html}), 200
        except Exception as e:
            current_app.logger.exception("Error generating AI feedback")
            sess.status = SessionStatus.SUBMITTED
            db.commit()
            return jsonify({"ok": False, "error": str(e)}), 500
    finally:
        db.close()


@oral_bp.route("/session/<int:session_id>/phase-feedback/<int:phase>", methods=["POST"])
def phase_feedback(session_id: int, phase: int):
    if phase not in (1, 2, 3):
        return jsonify({"ok": False, "error": "Invalid phase"}), 400

    db = SessionLocal()
    try:
        sess = db.query(Session).get(session_id)
        if not sess:
            return jsonify({"ok": False, "error": "Session not found"}), 404
        case = db.query(Case).get(sess.case_id) if sess else None
        case_payload = None
        if case:
            try:
                case_payload = load_case(case.case_code)
            except FileNotFoundError:
                case_payload = None

        if os.getenv("DISABLE_AI_FEEDBACK") == "1":
            return jsonify({"ok": False, "error": "AI feedback disabled"}), 503

        try:
            payload = request.get_json(silent=True) or {}
            scope = payload.get("scope")
            force = bool(payload.get("force"))
            scope_key = None
            if phase == 2 and scope in ("investigations", "diagnosis"):
                scope_key = scope

            if (
                phase == 2
                and scope_key == "investigations"
                and sess.phase2_investigations_locked
            ):
                return jsonify(
                    {
                        "ok": False,
                        "error": (
                            "Investigation feedback has already been provided and "
                            "cannot be regenerated. You may continue with interpretation "
                            "and diagnosis."
                        ),
                    }
                ), 409

            feedback_key = f"phase{phase}_feedback" if not scope_key else f"phase{phase}_{scope_key}_feedback"
            score_key = f"phase{phase}_scores" if not scope_key else f"phase{phase}_{scope_key}_scores"
            hash_key = f"{feedback_key}__hash"

            def _text_len(val):
                return len(val.strip()) if isinstance(val, str) else 0

            current_app.logger.info(
                "PHASE_FEEDBACK READ hpc=%r mh=%r exp=%r soc=%r diet=%r prev=%r",
                sess.hpc_notes,
                sess.medical_history_notes,
                sess.expectations_notes,
                sess.social_history_notes,
                sess.diet_notes,
                sess.preventive_regime_notes,
            )
            current_app.logger.info(
                "Phase feedback request phase=%s scope=%s force=%s lens=%s",
                phase,
                scope_key,
                force,
                {
                    "hpc_notes": _text_len(sess.hpc_notes),
                    "medical_history_notes": _text_len(sess.medical_history_notes),
                    "expectations_notes": _text_len(sess.expectations_notes),
                    "social_history_notes": _text_len(sess.social_history_notes),
                    "diet_notes": _text_len(sess.diet_notes),
                    "preventive_regime_notes": _text_len(sess.preventive_regime_notes),
                    "radiograph_report": _text_len(sess.radiograph_report),
                    "test_justification": _text_len(sess.test_justification),
                    "investigation_notes": _text_len(sess.investigation_notes),
                    "diagnoses": _text_len(sess.diagnoses),
                    "risk_assessment": _text_len(sess.risk_assessment),
                    "prevention_plan": _text_len(sess.prevention_plan),
                    "rehab_options": _text_len(sess.rehab_options),
                    "operative_options": _text_len(sess.operative_options),
                    "patient_preferences": _text_len(sess.patient_preferences),
                    "final_plan_and_consent_notes": _text_len(sess.final_plan_and_consent_notes),
                    "selected_tests": len(sess.selected_tests or []),
                },
            )

            if not force and sess.feedback_json and sess.feedback_json.get(feedback_key):
                if phase == 1:
                    cached_hash = (sess.feedback_json or {}).get(hash_key)
                    current_hash = phase1_hash(sess)
                    has_score = bool((sess.section_scores_json or {}).get(score_key))
                    if cached_hash == current_hash and has_score:
                        html = render_template(
                            "oral/_phase_feedback_block.html",
                            session=sess,
                            phase=phase,
                            feedback_key=feedback_key,
                            score_key=score_key,
                        )
                        return jsonify({"ok": True, "feedback_html": html, "cached": True}), 200
                else:
                    if phase == 2 and scope_key == "investigations" and not sess.phase2_investigations_locked:
                        sess.phase2_investigations_locked = True
                        db.commit()
                    html = render_template(
                        "oral/_phase_feedback_block.html",
                        session=sess,
                        phase=phase,
                        feedback_key=feedback_key,
                        score_key=score_key,
                    )
                    return jsonify({"ok": True, "feedback_html": html, "cached": True}), 200

            phase_feedback_data, phase_scores = generate_feedback_for_session_phase(
                sess,
                phase,
                scope=scope_key,
                case_payload=case_payload,
            )
            is_empty = (
                not phase_feedback_data.get("summary")
                and not (phase_feedback_data.get("strengths") or [])
                and not (phase_feedback_data.get("gaps") or [])
                and not (phase_feedback_data.get("unsafe_or_concerning") or [])
            )
            if is_empty:
                return jsonify({
                    "ok": False,
                    "error": "AI feedback failed (empty response). Check server logs for the OpenAI error."
                }), 502
            if phase == 2 and scope_key == "investigations":
                sess.phase2_investigations_locked = True

            feedback_json = dict(sess.feedback_json or {})
            section_scores = dict(sess.section_scores_json or {})
            feedback_json[feedback_key] = phase_feedback_data
            if phase == 1:
                feedback_json[hash_key] = phase1_hash(sess)
                attempt_key = "phase1_feedback_requests"
                attempt = int(section_scores.get(attempt_key) or 0) + 1
                section_scores[attempt_key] = attempt
                weight = phase1_weight(attempt)
                raw_score = phase_scores.get("score", 0)
                try:
                    raw_score_f = float(raw_score)
                except Exception:
                    raw_score_f = 0.0
                adjusted = round(raw_score_f * weight, 1)
                phase_scores = dict(phase_scores or {})
                phase_scores["score_raw"] = raw_score_f
                phase_scores["score"] = adjusted
                phase_scores["attempt"] = attempt
                phase_scores["weight"] = weight
            section_scores[score_key] = phase_scores

            sess.feedback_json = feedback_json
            sess.section_scores_json = section_scores
            flag_modified(sess, "feedback_json")
            flag_modified(sess, "section_scores_json")
            db.commit()
            db.refresh(sess)

            html = render_template(
                "oral/_phase_feedback_block.html",
                session=sess,
                phase=phase,
                feedback_key=feedback_key,
                score_key=score_key,
            )
            return jsonify({"ok": True, "feedback_html": html}), 200
        except Exception as e:
            current_app.logger.exception("Error generating phase feedback")
            return jsonify({"ok": False, "error": str(e)}), 500
    finally:
        db.close()


@oral_bp.route("/session/<int:session_id>/preview-tests", methods=["POST"])
def preview_tests(session_id: int):
    db = SessionLocal()
    try:
        sess = db.query(Session).get(session_id)
        if not sess:
            return jsonify({"ok": False, "error": "Session not found"}), 404

        payload = request.get_json(silent=True) or {}
        selected_tests = payload.get("selected_tests") or []
        if not isinstance(selected_tests, list):
            selected_tests = []

        case = db.query(Case).get(sess.case_id) if sess else None
        case_payload = {}
        if case:
            try:
                case_payload = load_case(case.case_code)
            except FileNotFoundError:
                case_payload = {}

        _, test_results = build_test_results(case_payload, selected_tests, audience="student")
        html = render_template("oral/_test_results.html", test_results=test_results)
        show_radiograph = any(r.get("type") == "radiograph" for r in test_results)

        return jsonify(
            {
                "ok": True,
                "html": html,
                "show_radiograph_report": bool(show_radiograph),
            }
        ), 200
    finally:
        db.close()


@oral_bp.route("/session/<int:session_id>/tts", methods=["POST"])
def tts(session_id: int):
    db = SessionLocal()
    try:
        sess = db.query(Session).get(session_id)
        if not sess:
            return jsonify({"ok": False, "error": "Session not found"}), 404
    finally:
        db.close()

    payload = request.get_json(silent=True) or {}
    text = (payload.get("text") or "").strip()
    if not text:
        return jsonify({"ok": False, "error": "No text"}), 400
    if len(text) > 1200:
        text = text[:1200] + "..."

    model = payload.get("model") or DEFAULT_TTS_MODEL
    voice = payload.get("voice") or DEFAULT_TTS_VOICE
    instructions = (payload.get("instructions") or "").strip()
    if not instructions:
        instructions = DEFAULT_TTS_INSTRUCTIONS

    try:
        current_app.logger.warning(
            "TTS called model=%s voice=%s format=%s text_len=%s instr_len=%s",
            model,
            voice,
            DEFAULT_TTS_FORMAT,
            len(text),
            len(instructions),
        )
        return Response(
            _iter_tts_audio_bytes(text, model=model, voice=voice, instructions=instructions),
            mimetype="audio/mpeg",
            headers={"Cache-Control": "no-store"},
        )
    except Exception:
        current_app.logger.exception("TTS failed")
        return jsonify({"ok": False, "error": "TTS failed"}), 502


@oral_bp.route("/session/<int:session_id>/chat", methods=["POST"])
def chat(session_id: int):
    db = SessionLocal()
    try:
        sess = db.query(Session).get(session_id)
        if not sess:
            return jsonify({"ok": False, "error": "Session not found"}), 404

        payload = request.get_json(silent=True) or {}
        user_msg = (payload.get("message") or "").strip()
        phase = int(payload.get("phase") or 1)
        source = payload.get("source", "text")

        if not user_msg:
            return jsonify({"ok": False, "error": "Empty message"}), 400

        case = db.query(Case).get(sess.case_id)
        case_payload = {}
        if case:
            try:
                case_payload = load_case(case.case_code)
            except FileNotFoundError:
                case_payload = {}

        # Load existing chat log from DB; migrate legacy cookie log once if present
        chat_log = list(sess.chat_log or [])
        legacy_key = f"chat_log_{session_id}"
        legacy_log = flask_session.get(legacy_key, [])
        if legacy_log and not chat_log:
            chat_log = legacy_log

        chat_log.append({
            "role": "user",
            "content": user_msg,
            "phase": phase,
            "source": source,
            "ts": datetime.utcnow().isoformat()
        })

        # Call OpenAI-backed patient chat
        reply = patient_chat_reply(case_payload, chat_log, phase, user_msg)

        chat_log.append({
            "role": "assistant",
            "content": reply,
            "phase": phase,
            "source": "assistant",
            "ts": datetime.utcnow().isoformat()
        })

        sess.chat_log = chat_log
        flag_modified(sess, "chat_log")
        db.commit()

        if legacy_key in flask_session:
            flask_session.pop(legacy_key, None)

        return jsonify({"ok": True, "reply": reply})
    finally:
        db.close()
