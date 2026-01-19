import os
import json
import re
import logging
from openai import OpenAI

API_KEY = os.getenv("OPENAI_API_KEY")
# Fail fast if calls hang — override via OPENAI_TIMEOUT_SECONDS if needed
OPENAI_TIMEOUT = float(os.getenv("OPENAI_TIMEOUT_SECONDS", "15"))

client = OpenAI(
    api_key=API_KEY,
    timeout=OPENAI_TIMEOUT,
    max_retries=0,
) if API_KEY else None

# Prefer a reliable JSON-capable model; allow override via env.
PREFERRED_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
logger = logging.getLogger(__name__)


def build_feedback_prompt(session_data: dict) -> str:
    """
    Build a single big prompt from all three phases of the student's notes.
    This is Option A: one end-of-case feedback message.
    """

    def s(val):
        if isinstance(val, str):
            return val.strip()
        return val

    return f"""
You are an experienced oral health educator marking a dental student.

IMPORTANT RULES (do not break these):
- Grade ONLY what the student explicitly wrote in the fields below.
- Do NOT infer actions or knowledge that are not written.
- Do NOT use clinical common sense to fill gaps.
- If the student did not write something, treat it as not done.
- Every positive claim MUST include a direct quote from the student as evidence.
- If you cannot quote it, you must NOT praise it.
- Evidence quotes must be verbatim substrings from the free-text fields only:
  hpc_notes, medical_history_notes, expectations_notes, social_history_notes,
  diet_notes, preventive_regime_notes, radiograph_report, investigation_notes,
  diagnoses, risk_assessment, prevention_plan, rehab_options, operative_options,
  patient_preferences, final_plan_and_consent_notes.
- Do NOT use selected_tests or any clinician truth as evidence.

STUDENT SUBMISSION (only source of truth):

PHASE 1 – INFORMATION GATHERING
HPC:
{s(session_data.get('hpc_notes', ''))}

Medical history:
{s(session_data.get('medical_history_notes', ''))}

Expectations:
{s(session_data.get('expectations_notes', ''))}

Social history:
{s(session_data.get('social_history_notes', ''))}

Diet:
{s(session_data.get('diet_notes', ''))}

Preventive regime:
{s(session_data.get('preventive_regime_notes', ''))}

PHASE 2 – INVESTIGATIONS / DIAGNOSIS / RISK
Selected tests:
{session_data.get('selected_tests', [])}

Radiograph report:
{s(session_data.get('radiograph_report', ''))}

Investigation notes:
{s(session_data.get('investigation_notes', ''))}

Diagnoses:
{s(session_data.get('diagnoses', ''))}

Risk assessment:
{s(session_data.get('risk_assessment', ''))}

PHASE 3 – PLANNING / CONSENT
Prevention plan:
{s(session_data.get('prevention_plan', ''))}

Rehab options:
{s(session_data.get('rehab_options', ''))}

Operative options:
{s(session_data.get('operative_options', ''))}

Patient preferences:
{s(session_data.get('patient_preferences', ''))}

Final plan & consent notes:
{s(session_data.get('final_plan_and_consent_notes', ''))}

OUTPUT JSON ONLY in this schema:

{{
  "feedback": {{
    "history_and_information": {{
      "strengths": [{{"comment": "...", "evidence": "DIRECT QUOTE FROM STUDENT"}}],
      "gaps": [{{"comment": "...", "expected": "...", "evidence": ""}}],
      "unsafe_or_concerning": [{{"comment": "...", "evidence": "DIRECT QUOTE (or empty if none)"}}]
    }},
    "investigations_and_diagnosis": {{
      "strengths": [...],
      "gaps": [...],
      "unsafe_or_concerning": [...]
    }},
    "planning_and_consent": {{
      "strengths": [...],
      "gaps": [...],
      "unsafe_or_concerning": [...]
    }},
    "overall_summary": "2-4 sentences max. No praise without evidence."
  }}
}}

Scoring rules:
- If a section is basically empty, score 0-2 and say it is incomplete.
- Do not reward selected tests unless the student documented findings/interpretation in writing.
    """.strip()


def build_scores_prompt(session_data: dict) -> str:
    def s(val):
        if isinstance(val, str):
            return val.strip()
        return val

    return f"""
You are an experienced oral health educator marking a dental student.

IMPORTANT RULES (do not break these):
- Grade ONLY what the student explicitly wrote in the fields below.
- Do NOT infer actions or knowledge that are not written.
- Do NOT use clinical common sense to fill gaps.
- If the student did not write something, treat it as not done.

STUDENT SUBMISSION (only source of truth):

PHASE 1 – INFORMATION GATHERING
HPC:
{s(session_data.get('hpc_notes', ''))}

Medical history:
{s(session_data.get('medical_history_notes', ''))}

Expectations:
{s(session_data.get('expectations_notes', ''))}

Social history:
{s(session_data.get('social_history_notes', ''))}

Diet:
{s(session_data.get('diet_notes', ''))}

Preventive regime:
{s(session_data.get('preventive_regime_notes', ''))}

PHASE 2 – INVESTIGATIONS / DIAGNOSIS / RISK
Selected tests:
{session_data.get('selected_tests', [])}

Radiograph report:
{s(session_data.get('radiograph_report', ''))}

Investigation notes:
{s(session_data.get('investigation_notes', ''))}

Diagnoses:
{s(session_data.get('diagnoses', ''))}

Risk assessment:
{s(session_data.get('risk_assessment', ''))}

PHASE 3 – PLANNING / CONSENT
Prevention plan:
{s(session_data.get('prevention_plan', ''))}

Rehab options:
{s(session_data.get('rehab_options', ''))}

Operative options:
{s(session_data.get('operative_options', ''))}

Patient preferences:
{s(session_data.get('patient_preferences', ''))}

Final plan & consent notes:
{s(session_data.get('final_plan_and_consent_notes', ''))}

OUTPUT JSON ONLY in this schema:
{{
  "scores": {{
    "history_and_information": 0-10,
    "investigations_and_diagnosis": 0-10,
    "planning_and_consent": 0-10,
    "overall": 0-10
  }}
}}

Scoring rules:
- If a section is basically empty, score 0-2 and say it is incomplete.
- Do not reward selected tests unless the student documented findings/interpretation in writing.
    """.strip()


def generate_feedback_for_session_phase(session, phase: int, scope: str | None = None) -> tuple[dict, dict]:
    """
    Generate phase-only feedback and score.

    Returns:
        phase_feedback: dict with strengths/gaps/unsafe_or_concerning/summary
        phase_scores: dict with {"score": 0-10}
    """
    if phase == 1:
        fields = {
            "hpc_notes": session.hpc_notes,
            "medical_history_notes": session.medical_history_notes,
            "expectations_notes": session.expectations_notes,
            "social_history_notes": session.social_history_notes,
            "diet_notes": session.diet_notes,
            "preventive_regime_notes": session.preventive_regime_notes,
        }
        phase_name = "PHASE 1 – INFORMATION GATHERING"
    elif phase == 2:
        if scope == "investigations":
            fields = {
                "selected_tests": session.selected_tests or [],
                "radiograph_report": session.radiograph_report,
                "investigation_notes": session.investigation_notes,
            }
            phase_name = "PHASE 2A – INVESTIGATIONS & REPORT"
        elif scope == "diagnosis":
            fields = {
                "diagnoses": session.diagnoses,
                "risk_assessment": session.risk_assessment,
            }
            phase_name = "PHASE 2B – DIAGNOSIS & RISK ASSESSMENT"
        else:
            fields = {
                "selected_tests": session.selected_tests or [],
                "radiograph_report": session.radiograph_report,
                "investigation_notes": session.investigation_notes,
                "diagnoses": session.diagnoses,
                "risk_assessment": session.risk_assessment,
            }
            phase_name = "PHASE 2 – INVESTIGATIONS / DIAGNOSIS / RISK"
    else:
        fields = {
            "prevention_plan": session.prevention_plan,
            "rehab_options": session.rehab_options,
            "operative_options": session.operative_options,
            "patient_preferences": session.patient_preferences,
            "final_plan_and_consent_notes": session.final_plan_and_consent_notes,
        }
        phase_name = "PHASE 3 – PLANNING / CONSENT"

    def _has_text(val):
        return isinstance(val, str) and val.strip()

    any_text = any(_has_text(v) for k, v in fields.items() if k != "selected_tests")
    tests_selected = bool(fields.get("selected_tests")) if phase == 2 else False
    if not any_text:
        if phase == 2 and tests_selected and scope != "diagnosis":
            return (
                {
                    "strengths": [],
                    "gaps": [
                        {
                            "comment": "Tests were selected, but no interpretation or findings were written.",
                            "expected": "Write a radiograph report and/or investigation notes, plus diagnoses and a risk assessment.",
                            "evidence": "",
                        }
                    ],
                    "unsafe_or_concerning": [],
                    "summary": "Tests were selected but nothing was documented.",
                },
                {"score": 1},
            )
        if phase == 2 and scope == "diagnosis":
            return (
                {
                    "strengths": [],
                    "gaps": [
                        {
                            "comment": "No diagnosis or risk assessment was provided.",
                            "expected": "Document diagnoses and risk assessment before requesting feedback.",
                            "evidence": "",
                        }
                    ],
                    "unsafe_or_concerning": [],
                    "summary": "No diagnosis or risk assessment was documented yet.",
                },
                {"score": 0},
            )
        return (
            {
                "strengths": [],
                "gaps": [
                    {
                        "comment": "No content provided for this phase.",
                        "expected": "Complete the fields before requesting feedback.",
                        "evidence": "",
                    }
                ],
                "unsafe_or_concerning": [],
                "summary": "Nothing was written in this phase yet.",
            },
            {"score": 0},
        )

    def s(val):
        if isinstance(val, str):
            return val.strip()
        return val

    payload = {k: s(v) for k, v in fields.items()}
    prompt = f"""
You are an experienced oral health educator marking a dental student.

IMPORTANT RULES (do not break these):
- Grade ONLY what the student explicitly wrote in the fields below.
- Do NOT infer actions or knowledge that are not written.
- If the student did not write something, treat it as not done.
- Every positive claim MUST include a direct quote from the student's free-text as evidence.
- Evidence must be a verbatim substring from the student's free-text fields. Do NOT use selected_tests as evidence.

{phase_name}
STUDENT FIELDS:
{json.dumps(payload, ensure_ascii=True, indent=2)}

Return ONLY JSON in this schema:
{{
  "feedback": {{
    "strengths": [{{"comment":"...","evidence":"DIRECT QUOTE"}}],
    "gaps": [{{"comment":"...","expected":"...","evidence":""}}],
    "unsafe_or_concerning": [{{"comment":"...","evidence":"DIRECT QUOTE (or empty if none)"}}],
    "summary": "1-2 sentences. No praise without evidence."
  }},
  "score": 0-10
}}
""".strip()

    if not client:
        return (
            {
                "strengths": [],
                "gaps": [
                    {
                        "comment": "AI feedback unavailable (missing API key).",
                        "expected": "",
                        "evidence": "",
                    }
                ],
                "unsafe_or_concerning": [],
                "summary": "AI feedback unavailable.",
            },
            {"score": 0},
        )

    def _extract_content(resp):
        msg = resp.choices[0].message
        content = msg.content
        if isinstance(content, list):
            if content and hasattr(content[0], "text"):
                return content[0].text or ""
            if content and isinstance(content[0], dict) and "text" in content[0]:
                return content[0]["text"] or ""
            return ""
        return content or ""

    def _repair_json(raw_text: str, schema_hint: str):
        repair_prompt = (
            "You are a JSON repair utility.\n"
            "Fix ONLY syntax/quoting/brackets/commas so the JSON becomes valid.\n"
            "Do NOT add new content beyond what is already present.\n"
            "Return ONLY valid JSON matching this schema:\n"
            f"{schema_hint}\n\n"
            "Invalid JSON:\n"
            f"{raw_text}"
        )
        return client.chat.completions.create(
            model=PREFERRED_MODEL,
            messages=[{"role": "user", "content": repair_prompt}],
            max_completion_tokens=500,
            temperature=0.0,
            response_format={"type": "json_object"},
        )

    raw = ""
    try:
        resp = client.chat.completions.create(
            model=PREFERRED_MODEL,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.2,
            response_format={"type": "json_object"},
            max_completion_tokens=900,
        )
        raw = _extract_content(resp)
        parsed = json.loads(raw)
    except Exception:
        schema_hint = """{
  "feedback": {
    "strengths": [],
    "gaps": [],
    "unsafe_or_concerning": [],
    "summary": ""
  },
  "score": 0
}"""
        try:
            repair_resp = _repair_json(raw, schema_hint)
            repaired = _extract_content(repair_resp)
            parsed = json.loads(repaired) if repaired else {}
        except Exception:
            parsed = {}

    fb = parsed.get("feedback") if isinstance(parsed, dict) else {}
    score = parsed.get("score", 0) if isinstance(parsed, dict) else 0

    output = {
        "strengths": fb.get("strengths") if isinstance(fb.get("strengths"), list) else [],
        "gaps": fb.get("gaps") if isinstance(fb.get("gaps"), list) else [],
        "unsafe_or_concerning": (
            fb.get("unsafe_or_concerning") if isinstance(fb.get("unsafe_or_concerning"), list) else []
        ),
        "summary": fb.get("summary") if isinstance(fb.get("summary"), str) else "",
    }

    def _all_student_text(payload_dict: dict) -> str:
        parts = []
        for k, v in payload_dict.items():
            if k == "selected_tests":
                continue
            if isinstance(v, str) and v.strip():
                parts.append(v.strip())
        return "\n".join(parts)

    def _norm_text(val: str) -> str:
        normalized = (val or "").lower()
        normalized = normalized.replace("“", '"').replace("”", '"').replace("’", "'")
        normalized = re.sub(r"\s+", " ", normalized).strip()
        return normalized

    def _evidence_present(evidence: str, student_text: str) -> bool:
        if not evidence:
            return False
        return _norm_text(evidence) in _norm_text(student_text)

    def _ensure_item_dict(item, keys):
        if isinstance(item, dict):
            return {k: item.get(k, "") for k in keys}
        return {k: "" for k in keys}

    def _prune_list(items, student_text, allow_empty_evidence=False):
        cleaned = []
        for it in items or []:
            it = _ensure_item_dict(it, ("comment", "evidence", "expected"))
            evidence = (it.get("evidence") or "").strip()[:240]
            if allow_empty_evidence:
                it["evidence"] = evidence
                cleaned.append(it)
            else:
                if _evidence_present(evidence, student_text):
                    it["evidence"] = evidence
                    cleaned.append(it)
        return cleaned

    student_text = _all_student_text(payload)
    output["strengths"] = _prune_list(output["strengths"], student_text, allow_empty_evidence=False)
    output["gaps"] = [
        _ensure_item_dict(it, ("comment", "expected", "evidence")) for it in (output["gaps"] or [])
    ]

    unsafe_clean = []
    for it in output["unsafe_or_concerning"] or []:
        it = _ensure_item_dict(it, ("comment", "evidence", "expected"))
        evidence = (it.get("evidence") or "").strip()[:240]
        if not evidence or _evidence_present(evidence, student_text):
            it["evidence"] = evidence
            unsafe_clean.append(it)
    output["unsafe_or_concerning"] = unsafe_clean

    try:
        score_val = int(round(float(score)))
    except Exception:
        score_val = 0
    score_val = max(0, min(10, score_val))
    return output, {"score": score_val}


def generate_feedback_for_session(session) -> tuple[dict, dict, float]:
    """
    Call GPT-5 to generate feedback for a given Session object.

    Returns:
        feedback_dict (for feedback_json),
        scores_dict (for section_scores_json),
        overall_score (float)
    """

    # Prepare data from the SQLAlchemy Session object
    data = {
        "hpc_notes": session.hpc_notes,
        "medical_history_notes": session.medical_history_notes,
        "expectations_notes": session.expectations_notes,
        "social_history_notes": session.social_history_notes,
        "diet_notes": session.diet_notes,
        "preventive_regime_notes": session.preventive_regime_notes,
        "selected_tests": session.selected_tests or [],
        "radiograph_report": session.radiograph_report,
        "investigation_notes": session.investigation_notes,
        "diagnoses": session.diagnoses,
        "risk_assessment": session.risk_assessment,
        "prevention_plan": session.prevention_plan,
        "rehab_options": session.rehab_options,
        "operative_options": session.operative_options,
        "patient_preferences": session.patient_preferences,
        "final_plan_and_consent_notes": session.final_plan_and_consent_notes,
    }

    def _has_text(val):
        return isinstance(val, str) and val.strip()

    # Simple per-section presence checks to avoid hallucinated positive feedback
    history_present = any(
        _has_text(data.get(k))
        for k in (
            "hpc_notes",
            "medical_history_notes",
            "expectations_notes",
            "social_history_notes",
            "diet_notes",
            "preventive_regime_notes",
        )
    )
    investigations_written = any(
        _has_text(data.get(k))
        for k in (
            "radiograph_report",
            "investigation_notes",
            "diagnoses",
            "risk_assessment",
        )
    )
    tests_selected = bool(data.get("selected_tests"))
    planning_present = any(
        _has_text(data.get(k))
        for k in (
            "prevention_plan",
            "rehab_options",
            "operative_options",
            "patient_preferences",
            "final_plan_and_consent_notes",
        )
    )

    any_content = any(
        _has_text(v) for k, v in data.items() if k != "selected_tests"
    ) or bool(data.get("selected_tests"))

    # If no API key, bail out gracefully instead of hanging the worker
    if not client:
        fallback_feedback = {
            "history_and_information": {
                "strengths": [],
                "gaps": [],
                "unsafe_or_concerning": [],
            },
            "investigations_and_diagnosis": {
                "strengths": [],
                "gaps": [],
                "unsafe_or_concerning": [],
            },
            "planning_and_consent": {
                "strengths": [],
                "gaps": [],
                "unsafe_or_concerning": [],
            },
            "overall_summary": "AI feedback unavailable (missing API key).",
        }
        fallback_scores = {
            "history_and_information": 0,
            "investigations_and_diagnosis": 0,
            "planning_and_consent": 0,
            "overall": 0,
        }
        return fallback_feedback, fallback_scores, 0.0

    # If nothing was provided, short-circuit with zero scores.
    if not any_content:
        zero_feedback = {
            "history_and_information": {
                "strengths": [],
                "gaps": [
                    {
                        "comment": "No history or information was provided.",
                        "expected": "Complete the Phase 1 fields.",
                        "evidence": "",
                    }
                ],
                "unsafe_or_concerning": [],
            },
            "investigations_and_diagnosis": {
                "strengths": [],
                "gaps": [
                    {
                        "comment": "No investigations or diagnoses were provided.",
                        "expected": "Document investigations, diagnoses, and risk assessment.",
                        "evidence": "",
                    }
                ],
                "unsafe_or_concerning": [],
            },
            "planning_and_consent": {
                "strengths": [],
                "gaps": [
                    {
                        "comment": "No planning or consent details were provided.",
                        "expected": "Document planning, options, preferences, and consent.",
                        "evidence": "",
                    }
                ],
                "unsafe_or_concerning": [],
            },
            "overall_summary": "No data was submitted for this case.",
        }
        zero_scores = {
            "history_and_information": 0,
            "investigations_and_diagnosis": 0,
            "planning_and_consent": 0,
            "overall": 0,
        }
        return zero_feedback, zero_scores, 0.0

    feedback_prompt = build_feedback_prompt(data)
    scores_prompt = build_scores_prompt(data)

    def _try_json_call(model: str, max_tokens: int, prompt_text: str):
        return client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": prompt_text}],
            max_completion_tokens=max_tokens,
            temperature=0.2,
            response_format={"type": "json_object"},
        )

    def _extract_content(resp):
        msg = resp.choices[0].message
        content = msg.content
        if isinstance(content, list):
            if content and hasattr(content[0], "text"):
                return content[0].text or ""
            if content and isinstance(content[0], dict) and "text" in content[0]:
                return content[0]["text"] or ""
            return ""
        return content or ""

    attempted = []

    def _repair_json(raw_text: str, schema_hint: str):
        repair_prompt = (
            "You are a JSON repair utility.\n"
            "Fix ONLY syntax/quoting/brackets/commas so the JSON becomes valid.\n"
            "Do NOT add new content beyond what is already present.\n"
            "Return ONLY valid JSON matching this schema:\n"
            f"{schema_hint}\n\n"
            "Invalid JSON:\n"
            f"{raw_text}"
        )
        return client.chat.completions.create(
            model=PREFERRED_MODEL,
            messages=[{"role": "user", "content": repair_prompt}],
            max_completion_tokens=700,
            temperature=0.0,
            response_format={"type": "json_object"},
        )

    def _fallback_feedback(message: str):
        return {
            "history_and_information": {
                "strengths": [],
                "gaps": [{"comment": message, "expected": "", "evidence": ""}],
                "unsafe_or_concerning": [],
            },
            "investigations_and_diagnosis": {
                "strengths": [],
                "gaps": [{"comment": message, "expected": "", "evidence": ""}],
                "unsafe_or_concerning": [],
            },
            "planning_and_consent": {
                "strengths": [],
                "gaps": [{"comment": message, "expected": "", "evidence": ""}],
                "unsafe_or_concerning": [],
            },
            "overall_summary": message,
        }

    def _call_json_with_repair(prompt_text: str, token_sizes: tuple[int, ...], schema_hint: str):
        response = None
        raw_json = ""
        for model in models_to_try:
            for max_tokens in token_sizes:
                try:
                    response = _try_json_call(model, max_tokens, prompt_text)
                    raw_json = _extract_content(response)
                    finish = response.choices[0].finish_reason
                    attempted.append((model, max_tokens, finish))
                    if finish == "length":
                        raw_json = ""
                        continue
                    if raw_json:
                        break
                except Exception as e:
                    attempted.append((model, max_tokens, f"error:{e}"))
                    continue
            if raw_json:
                break

        if not raw_json:
            return None, None

        try:
            return json.loads(raw_json), raw_json
        except Exception:
            try:
                repair_resp = _repair_json(raw_json, schema_hint)
                repaired = _extract_content(repair_resp)
                if repaired:
                    return json.loads(repaired), repaired
            except Exception:
                return None, raw_json
        return None, raw_json

    models_to_try = [PREFERRED_MODEL]
    if "gpt-4o-mini" not in models_to_try:
        models_to_try.append("gpt-4o-mini")
    if "gpt-4o" not in models_to_try:
        models_to_try.append("gpt-4o")

    feedback_schema = """{
  "feedback": {
    "history_and_information": {"strengths": [], "gaps": [], "unsafe_or_concerning": []},
    "investigations_and_diagnosis": {"strengths": [], "gaps": [], "unsafe_or_concerning": []},
    "planning_and_consent": {"strengths": [], "gaps": [], "unsafe_or_concerning": []},
    "overall_summary": ""
  }
}"""
    scores_schema = """{
  "scores": {
    "history_and_information": 0,
    "investigations_and_diagnosis": 0,
    "planning_and_consent": 0,
    "overall": 0
  }
}"""

    parsed_feedback, raw_feedback = _call_json_with_repair(
        feedback_prompt,
        (2200, 1800, 1400),
        feedback_schema,
    )
    parsed_scores, raw_scores = _call_json_with_repair(
        scores_prompt,
        (300, 200, 150),
        scores_schema,
    )

    if not parsed_feedback and not parsed_scores:
        logger.warning(
            "AI feedback generation failed; using fallback. attempts=%s feedback=%r scores=%r",
            attempted,
            (raw_feedback or "")[:500],
            (raw_scores or "")[:500],
        )
        feedback = _fallback_feedback(
            "Feedback could not be generated due to a formatting error. Please retry."
        )
        scores = {
            "history_and_information": 0,
            "investigations_and_diagnosis": 0,
            "planning_and_consent": 0,
            "overall": 0,
        }
        overall = 0.0
        return feedback, scores, overall

    feedback_container = parsed_feedback.get("feedback") if isinstance(parsed_feedback, dict) else None
    if not isinstance(feedback_container, dict):
        feedback_container = None
    feedback = feedback_container or _fallback_feedback(
        "Feedback could not be generated due to a formatting error. Please retry."
    )

    scores_container = parsed_scores.get("scores") if isinstance(parsed_scores, dict) else None
    scores = scores_container if isinstance(scores_container, dict) else {}
    overall = scores.get("overall", None)
    for key in ("history_and_information", "investigations_and_diagnosis", "planning_and_consent"):
        if not isinstance(scores.get(key), (int, float)):
            scores[key] = 0

    def _ensure_section(obj):
        if not isinstance(obj, dict):
            return {"strengths": [], "gaps": [], "unsafe_or_concerning": []}
        strengths = obj.get("strengths")
        gaps = obj.get("gaps")
        concerns = obj.get("unsafe_or_concerning")
        obj["strengths"] = strengths if isinstance(strengths, list) else []
        obj["gaps"] = gaps if isinstance(gaps, list) else []
        obj["unsafe_or_concerning"] = concerns if isinstance(concerns, list) else []
        return obj

    for key in ("history_and_information", "investigations_and_diagnosis", "planning_and_consent"):
        feedback[key] = _ensure_section(feedback.get(key))
    if "overall_summary" not in feedback or not isinstance(feedback.get("overall_summary"), str):
        feedback["overall_summary"] = ""

    # Override sections that were left blank to avoid optimistic feedback
    def override_section(key: str, text: str, score_val: int):
        feedback[key] = {
            "strengths": [],
            "gaps": [
                {"comment": text, "expected": "", "evidence": ""},
            ],
            "unsafe_or_concerning": [],
        }
        scores[key] = score_val

    if not history_present:
        override_section(
            "history_and_information",
            "No history or information was provided. Please complete Phase 1 fields.",
            0,
        )

    if not investigations_written and not tests_selected:
        override_section(
            "investigations_and_diagnosis",
            "No investigations, reports, diagnoses, or risk assessment were provided.",
            0,
        )
    elif tests_selected and not investigations_written:
        override_section(
            "investigations_and_diagnosis",
            "Tests were selected, but no radiograph report, investigation notes, diagnoses, or risk assessment were documented. Please record your findings.",
            1,
        )

    if not planning_present:
        override_section(
            "planning_and_consent",
            "No planning, options, preferences, or consent notes were provided.",
            0,
        )

    # Recompute overall as the mean of the three section scores (if present), else 0
    section_keys = ("history_and_information", "investigations_and_diagnosis", "planning_and_consent")
    section_scores = [
        scores[k] for k in section_keys if isinstance(scores.get(k), (int, float))
    ]
    if section_scores:
        overall = sum(section_scores) / len(section_scores)
    else:
        overall = 0.0

    def _all_student_text(d: dict) -> str:
        parts = []
        for k, v in d.items():
            if k == "selected_tests":
                continue
            if isinstance(v, str) and v.strip():
                parts.append(v.strip())
        return "\n".join(parts)

    def _norm_text(val: str) -> str:
        normalized = val.lower()
        normalized = normalized.replace("“", '"').replace("”", '"').replace("’", "'")
        normalized = re.sub(r"\s+", " ", normalized).strip()
        return normalized

    def _evidence_present(evidence: str, student_text: str) -> bool:
        if not evidence:
            return False
        norm_evidence = _norm_text(evidence)
        norm_text = _norm_text(student_text)
        return norm_evidence and (norm_evidence in norm_text)

    def _prune_strengths(section_obj: dict, student_text: str) -> dict:
        strengths = section_obj.get("strengths") or []
        cleaned = []
        for item in strengths:
            evidence = (item.get("evidence") or "").strip()[:240]
            if _evidence_present(evidence, student_text):
                cleaned.append(item)
        section_obj["strengths"] = cleaned
        return section_obj

    student_text = _all_student_text(data)
    for key in ("history_and_information", "investigations_and_diagnosis", "planning_and_consent"):
        if isinstance(feedback.get(key), dict):
            feedback[key] = _prune_strengths(feedback[key], student_text)

    total_strengths = sum(
        len(feedback[key]["strengths"])
        for key in ("history_and_information", "investigations_and_diagnosis", "planning_and_consent")
        if isinstance(feedback.get(key), dict)
    )
    if total_strengths == 0:
        feedback["overall_summary"] = (
            "Feedback is limited because there were few or no evidenced strengths in the written submission. "
            "Complete the missing fields and add explicit interpretations to receive more detailed feedback."
        )

    overall_summary = feedback.get("overall_summary")
    if not isinstance(overall_summary, str) or not overall_summary.strip():
        feedback["overall_summary"] = (
            "Feedback is limited because some sections were left blank. "
            "Complete the missing fields and regenerate feedback."
        )
    overall = round(float(overall or 0.0), 2)
    scores["overall"] = overall

    return feedback, scores, overall
