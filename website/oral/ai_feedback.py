import os
import json
from openai import OpenAI

client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

# Prefer a reliable JSON-capable model; allow override via env.
PREFERRED_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini")


def build_feedback_prompt(session_data: dict) -> str:
    """
    Build a single big prompt from all three phases of the student's notes.
    This is Option A: one end-of-case feedback message.
    """

    return f"""
You are an experienced oral health educator. A dental student has completed an
oral health assessment case in three phases:

PHASE 1 – INFORMATION GATHERING
History of presenting complaint:
{session_data.get('hpc_notes', '')}

Medical history:
{session_data.get('medical_history_notes', '')}

Expectations of treatment and outcome:
{session_data.get('expectations_notes', '')}

Social history:
{session_data.get('social_history_notes', '')}

Dietary habits:
{session_data.get('diet_notes', '')}

Current preventive regime:
{session_data.get('preventive_regime_notes', '')}

PHASE 2 – INVESTIGATIONS, DIAGNOSES & RISK ASSESSMENT
Selected tests:
{session_data.get('selected_tests', [])}

Radiograph report:
{session_data.get('radiograph_report', '')}

Investigation notes:
{session_data.get('investigation_notes', '')}

Diagnoses:
{session_data.get('diagnoses', '')}

Risk assessment:
{session_data.get('risk_assessment', '')}

PHASE 3 – PLANNING, OPTIONS, PREFERENCES & CONSENT
Prevention & stabilisation plan:
{session_data.get('prevention_plan', '')}

Rehabilitation options:
{session_data.get('rehab_options', '')}

Operative / intervention options:
{session_data.get('operative_options', '')}

Discussion & patient preferences:
{session_data.get('patient_preferences', '')}

Final plan and consent notes:
{session_data.get('final_plan_and_consent_notes', '')}

TASK:
1. Provide constructive, educational feedback addressed directly to the student.
   Focus on:
   - How well they gathered information
   - Appropriateness and interpretation of investigations
   - Quality of diagnoses and risk assessment
   - Quality and realism of their plan and consent process

2. Give three separate section scores out of 10:
   - "history_and_information"
   - "investigations_and_diagnosis"
   - "planning_and_consent"

3. Compute an overall score out of 10, roughly the average, but adjusted by your judgement.
   If a section is blank or missing, score that section 0–2/10 and say why it is incomplete.

4. Return your answer as pure JSON only, with this structure:

{{
  "feedback": {{
    "history_and_information": "text feedback here...",
    "investigations_and_diagnosis": "text feedback here...",
    "planning_and_consent": "text feedback here...",
    "overall_summary": "short overall summary..."
  }},
  "scores": {{
    "history_and_information": 0-10 number,
    "investigations_and_diagnosis": 0-10 number,
    "planning_and_consent": 0-10 number,
    "overall": 0-10 number
  }}
}}

Do not include any extra commentary outside the JSON.
If some sections are blank or missing, explain that briefly in the feedback and score accordingly.
    """.strip()


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
    investigations_present = any(
        _has_text(data.get(k))
        for k in (
            "radiograph_report",
            "investigation_notes",
            "diagnoses",
            "risk_assessment",
        )
    ) or bool(data.get("selected_tests"))
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

    # If nothing was provided, short-circuit with zero scores.
    if not any_content:
        zero_feedback = {
            "history_and_information": "No history or information was provided.",
            "investigations_and_diagnosis": "No investigations or diagnoses were provided.",
            "planning_and_consent": "No planning or consent details were provided.",
            "overall_summary": "No data was submitted for this case.",
        }
        zero_scores = {
            "history_and_information": 0,
            "investigations_and_diagnosis": 0,
            "planning_and_consent": 0,
            "overall": 0,
        }
        return zero_feedback, zero_scores, 0.0

    prompt = build_feedback_prompt(data)

    def _try_json_call(model: str, max_tokens: int):
        return client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": prompt}],
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
    raw_json = ""
    response = None

    models_to_try = [PREFERRED_MODEL]
    if "gpt-4o-mini" not in models_to_try:
        models_to_try.append("gpt-4o-mini")
    if "gpt-4o" not in models_to_try:
        models_to_try.append("gpt-4o")

    for model in models_to_try:
        for max_tokens in (900, 600, 400):
            try:
                response = _try_json_call(model, max_tokens)
                raw_json = _extract_content(response)
                attempted.append((model, max_tokens, response.choices[0].finish_reason))
                if raw_json:
                    break
            except Exception as e:
                attempted.append((model, max_tokens, f"error:{e}"))
                continue
        if raw_json:
            break

    # Last-resort plain text ask without JSON enforcement
    if not raw_json:
        plain_prompt = prompt + "\n\nReturn ONLY JSON in the described schema."
        for model in models_to_try:
            try:
                response = client.chat.completions.create(
                    model=model,
                    messages=[{"role": "user", "content": plain_prompt}],
                    max_completion_tokens=400,
                    temperature=0.2,
                )
                raw_json = _extract_content(response)
                attempted.append((model, "plain", response.choices[0].finish_reason))
                if raw_json:
                    break
            except Exception as e:
                attempted.append((model, "plain", f"error:{e}"))
                continue

    if not raw_json:
        raise ValueError(f"Empty response content from model. Attempts: {attempted}")

    try:
        parsed = json.loads(raw_json)
    except Exception as e:
        # Surface the content to help debugging malformed JSON from the model
        raise ValueError(f"Failed to parse model JSON: {e}; content={raw_json!r}") from e

    feedback = parsed.get("feedback", {})
    scores = parsed.get("scores", {})
    overall = scores.get("overall", None)

    # Override sections that were left blank to avoid optimistic feedback
    def override_section(key: str, text: str, score_val: int):
        feedback[key] = text
        scores[key] = score_val

    if not history_present:
        override_section(
            "history_and_information",
            "No history or information was provided. Please complete Phase 1 fields.",
            0,
        )

    if not investigations_present:
        override_section(
            "investigations_and_diagnosis",
            "No investigations, reports, diagnoses, or risk assessment were provided.",
            0,
        )
    elif data.get("selected_tests") and not any(
        _has_text(data.get(k))
        for k in ("radiograph_report", "investigation_notes", "diagnoses", "risk_assessment")
    ):
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

    return feedback, scores, overall
