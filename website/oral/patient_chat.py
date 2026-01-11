import os
import re

from openai import OpenAI

client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
CHAT_MODEL = os.getenv("OPENAI_CHAT_MODEL", os.getenv("OPENAI_MODEL", "gpt-4o-mini"))
PATIENT_TONE = os.getenv("ORAL_PATIENT_TONE", "a Scottish female patient in her late 30s")
PATIENT_PRONUNCIATION = os.getenv("ORAL_PATIENT_PRONUNCIATION", "Scottish")


# ---------- helpers ----------

def sanitize_patient_text(text: str) -> str:
    """
    Defensive cleanup: remove common markdown/formatting that looks odd in chat UI.
    """
    if not text:
        return ""

    # Remove **bold**
    text = re.sub(r"\*\*(.*?)\*\*", r"\1", text)

    # Remove leading bullet points "- " or "* "
    lines = []
    for line in text.splitlines():
        line = re.sub(r"^\s*[-*]\s+", "", line)
        lines.append(line)
    text = "\n".join(lines)

    # Collapse excessive whitespace
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    return text


def _phase_rules(phase: int) -> str:
    phase = int(phase)
    if phase == 1:
        return (
            "Phase 1 (history-taking): Only talk about symptoms, timeline, triggers, severity, impact, concerns, "
            "medical history, social history, diet, and oral hygiene—but reveal details gradually."
        )
    if phase == 2:
        return (
            "Phase 2 (investigations): You may clarify history questions, but do NOT invent or reveal any examination "
            "findings, baseline findings, test results, or radiograph interpretation."
        )
    if phase == 3:
        return (
            "Phase 3 (planning/preferences): You may discuss your concerns, preferences, constraints (time/cost/anxiety), "
            "and consent questions. Do NOT give a diagnosis or recommend treatments."
        )
    return "Stay consistent with the patient record and reveal details gradually."


def build_patient_system_prompt(case_payload: dict, phase: int) -> str:
    patient = (case_payload or {}).get("patient", {})
    guardrails = (case_payload or {}).get("guardrails", {})
    history = (case_payload or {}).get("history_truth", {}) or {}
    prompts = (case_payload or {}).get("clarification_prompts", []) or []

    # Pull out key areas so we can instruct incremental disclosure per domain
    hpc = (history.get("hpc") or {})
    expectations = (history.get("expectations") or {})
    med = (history.get("medical_history") or {})
    social = (history.get("social_history") or {})
    prev = (history.get("preventive_regime") or {})
    diet = (history.get("dietary_habits") or {})

    style = guardrails.get("style", "friendly, cooperative, not overly verbose")
    do_not_volunteer = guardrails.get("do_not_volunteer", [])
    disclosure_rules = guardrails.get("disclosure_rules", [])

    return f"""
You are roleplaying as a REALISTIC dental patient in an oral health consultation tutor.

IDENTITY
- Name: {patient.get("name", "Unknown")}
- Persona: {patient.get("persona", "")}

TONE / STYLE
- {style}
- Tone: {PATIENT_TONE}
- Pronunciation: {PATIENT_PRONUNCIATION}
- Sound like a normal patient, not a clinician or an exam marking scheme.
- Do NOT use markdown, headings, bullet points, or labelled sections (e.g. no "Triggers:", no "**bold**").

CRITICAL BEHAVIOUR (REALISM)
- Default answer length: 1–2 sentences.
- Answer ONLY what was asked. Do not volunteer extra categories.
- If asked an open prompt like "tell me more", give ONE additional detail only, then stop.
- If asked about oral hygiene, start with brushing only unless asked specifically about floss/interdental aids/mouthwash/toothpaste/bleeding.
- If asked about pain, start with triggers + duration. Do not give a full structured history unless asked step-by-step.
- If asked something not in the record, say you are not sure / don’t remember.

BOUNDARIES
- Do NOT invent new medical/dental facts beyond the truth.
- Do NOT give a diagnosis.
- Do NOT recommend tests or treatments.
- Do NOT reveal baseline findings or radiograph findings unless explicitly part of HISTORY truth.
- Do not volunteer: {do_not_volunteer}
- Disclosure rules: {disclosure_rules}

PHASE CONTEXT
- {_phase_rules(phase)}

PATIENT TRUTH (use as memory, not as a script)
HPC:
- Attendance reason: {hpc.get("attendance_reason", "")}
- Summary: {hpc.get("summary", "")}
- Last checkup: {hpc.get("last_checkup", "")}

Expectations / concerns:
- {expectations.get("summary", "")}

Medical history:
- Conditions: {(med.get("conditions") or [])}
- Notes: {med.get("notes", "")}

Social history:
- Smoking: {social.get("smoking", "")}
- Alcohol: {social.get("alcohol", "")}
- Drugs: {social.get("recreational_drugs", "")}
- Stress/grinding: {social.get("stress", "")}

Preventive regime (ONLY reveal details if specifically asked):
- Brushing: {prev.get("brushing", "")}
- Interdental: {prev.get("interdental", "")}
- Mouthwash: {prev.get("mouthwash", "")}
- Toothpaste: {prev.get("toothpaste", "")}
- Previous clean: {prev.get("previous_clean", "")}

Dietary habits (ONLY reveal details if specifically asked):
- Coffee: {diet.get("coffee", "")}
- Tea: {diet.get("tea", "")}
- Gym drinks: {diet.get("gym_drinks", "")}
- Snacks: {diet.get("snacks", "")}

CLARIFICATION PROMPTS (only if the student asks something related):
{prompts}

Now respond as the patient to the student's message.
""".strip()


def patient_chat_reply(case_payload: dict, chat_log: list, phase: int, user_message: str) -> str:
    system = build_patient_system_prompt(case_payload, phase)

    # Keep only last ~12 messages to control token use
    trimmed = (chat_log or [])[-12:]

    messages = [{"role": "system", "content": system}]
    for m in trimmed:
        role = m.get("role")
        content = (m.get("content") or "").strip()
        if role in ("user", "assistant") and content:
            messages.append({"role": role, "content": content})

    messages.append({"role": "user", "content": user_message})

    resp = client.chat.completions.create(
        model=CHAT_MODEL,
        messages=messages,
        temperature=0.25,
        max_completion_tokens=160
    )

    out = (resp.choices[0].message.content or "").strip()
    return sanitize_patient_text(out)
