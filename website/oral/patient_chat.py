import os

from openai import OpenAI

client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
CHAT_MODEL = os.getenv("OPENAI_CHAT_MODEL", os.getenv("OPENAI_MODEL", "gpt-4o-mini"))


def build_patient_system_prompt(case_payload: dict, phase: int) -> str:
    patient = (case_payload or {}).get("patient", {})
    guardrails = (case_payload or {}).get("guardrails", {})
    history = (case_payload or {}).get("history_truth", {})
    prompts = (case_payload or {}).get("clarification_prompts", [])

    # Phase-specific rules (critical to stop the chat leaking clinical findings)
    phase_rules = {
        1: "You are in Phase 1 (history-taking). Answer using only the patient's history and guardrails.",
        2: "You are in Phase 2 (investigations). Do NOT invent test results, radiograph findings, or examination findings. Only answer clarifying questions from history/clarification prompts.",
        3: "You are in Phase 3 (planning/preferences). You may discuss concerns, preferences, constraints, and consent questions as a patient. Do NOT give diagnosis or recommend treatment."
    }.get(int(phase), "Stay consistent with the patient record and guardrails.")

    return f"""
You are roleplaying as a dental patient in an oral health consultation tutor.

PATIENT IDENTITY
- Name: {patient.get("name", "Unknown")}
- Persona: {patient.get("persona", "")}

GUARDRAILS
- Style: {guardrails.get("style", "friendly, cooperative")}
- Do not volunteer: {guardrails.get("do_not_volunteer", [])}
- Disclosure rules: {guardrails.get("disclosure_rules", [])}

KNOWN HISTORY (truth)
{history}

IMPORTANT CLINICAL BOUNDARIES
- Do NOT invent new medical/dental facts beyond the truth above.
- Do NOT give a diagnosis.
- Do NOT recommend tests/treatment.
- If asked about something not in the truth, say you are not sure / don’t remember.
- Do NOT reveal baseline findings or radiograph findings unless those are explicitly part of the HISTORY truth.

PHASE CONTEXT
{phase_rules}

CLARIFICATION PROMPTS (if relevant):
{prompts}

Now respond as the patient to the student's question.
""".strip()


def patient_chat_reply(case_payload: dict, chat_log: list, phase: int, user_message: str) -> str:
    system = build_patient_system_prompt(case_payload, phase)

    # Keep only last ~12 messages to control token use
    trimmed = (chat_log or [])[-12:]

    messages = [{"role": "system", "content": system}]
    for m in trimmed:
        role = m.get("role")
        content = m.get("content", "")
        if role in ("user", "assistant") and content:
            messages.append({"role": role, "content": content})

    messages.append({"role": "user", "content": user_message})

    resp = client.chat.completions.create(
        model=CHAT_MODEL,
        messages=messages,
        temperature=0.4
    )

    return (resp.choices[0].message.content or "").strip()
