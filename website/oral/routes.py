import os
from datetime import datetime

from flask import Blueprint, redirect, render_template, request, url_for, jsonify, session as flask_session, current_app, Response
from openai import OpenAI
from sqlalchemy.orm.attributes import flag_modified

from .ai_feedback import generate_feedback_for_session
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
    "British female dental patient. Natural UK pacing and intonation. Avoid American pronunciation.",
)


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


@oral_bp.route("/")
def welcome():
    return render_template("oral/welcome.html")


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
    return render_template(
        "oral/admin_sessions.html",
        sessions=sessions,
        cases=cases,
        case_payloads=case_payloads,
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
            sess.hpc_notes = request.form.get("hpc_notes")
            sess.medical_history_notes = request.form.get("medical_history_notes")
            sess.expectations_notes = request.form.get("expectations_notes")
            sess.social_history_notes = request.form.get("social_history_notes")
            sess.diet_notes = request.form.get("diet_notes")
            sess.preventive_regime_notes = request.form.get("preventive_regime_notes")
            if not sess.phase1_completed_at:
                sess.phase1_completed_at = datetime.utcnow()
            db.commit()
            return redirect(url_for("oral.phase2", session_id=session_id))
    finally:
        db.close()

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
            sess.selected_tests = request.form.getlist("selected_tests")
            if "radiograph_report" in request.form:
                sess.radiograph_report = request.form.get("radiograph_report")
            sess.investigation_notes = request.form.get("investigation_notes")
            sess.diagnoses = request.form.get("diagnoses")
            sess.risk_assessment = request.form.get("risk_assessment")
            if not sess.phase2_completed_at:
                sess.phase2_completed_at = datetime.utcnow()
            action = request.form.get("action", "continue")
            db.commit()
            if action == "save":
                return redirect(url_for("oral.phase2", session_id=session_id))
            return redirect(url_for("oral.phase3", session_id=session_id))
    finally:
        db.close()

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
            sess.prevention_plan = request.form.get("prevention_plan")
            sess.rehab_options = request.form.get("rehab_options")
            sess.operative_options = request.form.get("operative_options")
            sess.patient_preferences = request.form.get("patient_preferences")
            sess.final_plan_and_consent_notes = request.form.get("final_plan_and_consent_notes")

            if not sess.phase3_completed_at:
                sess.phase3_completed_at = datetime.utcnow()
            sess.completed_at = datetime.utcnow()
            sess.status = SessionStatus.SUBMITTED

            # Generate feedback synchronously unless disabled
            if os.getenv("DISABLE_AI_FEEDBACK") == "1":
                db.commit()
                return redirect(url_for("oral.completed", session_id=session_id))

            try:
                feedback, scores, overall = generate_feedback_for_session(sess)
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
    finally:
        db.close()

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

        if os.getenv("DISABLE_AI_FEEDBACK") == "1":
            return jsonify({"ok": False, "error": "AI feedback disabled"}), 503

        # If already marked with feedback, return it
        if sess.status == SessionStatus.MARKED and sess.feedback_json:
            html = render_template("oral/_feedback_block.html", session=sess)
            return jsonify({"ok": True, "status": "marked", "feedback_html": html}), 200

        # Generate synchronously
        try:
            feedback, scores, overall = generate_feedback_for_session(sess)
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
