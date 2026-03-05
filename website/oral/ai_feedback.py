import os
import json
import re
import logging
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
  diet_notes, preventive_regime_notes, test_justification, radiograph_report, investigation_notes,
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

Test justification:
{s(session_data.get('test_justification', ''))}

Radiograph report:
{s(session_data.get('radiograph_report', ''))}

Investigation notes:
{s(session_data.get('investigation_notes', ''))}

Diagnoses:
{s(session_data.get('diagnoses', ''))}

Risk assessment:
{s(session_data.get('risk_assessment', ''))}

NOTE: Radiograph interpretation may be documented in either the radiograph report or investigation notes.

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

Test justification:
{s(session_data.get('test_justification', ''))}

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


# --- STRICT, CRITERION-LEVEL MARKING (Phase 1) -----------------------------

PHASE1_CRITERIA_MAX = {
    # Reason for attendance / HPC
    "hpc_reason_for_attendance": 1.0,
    "hpc_identification_of_symptoms": 1.0,
    "hpc_site": 1.0,
    "hpc_onset": 0.75,
    "hpc_character": 1.0,
    "hpc_progression": 0.75,
    "hpc_radiation": 0.5,
    "hpc_associated_symptoms": 0.25,
    "hpc_timing_patterns": 0.5,
    "hpc_exacerbating_relieving": 0.5,
    "hpc_severity": 0.25,
    # Medical history
    "mh_cardiovascular": 1.0,
    "mh_respiratory": 1.0,
    "mh_other_systemic": 0.5,
    "mh_gastrointestinal_reflux": 0.75,
    "mh_genitourinary": 0.25,
    "mh_medications": 1.0,
    "mh_recent_hospitalisations": 0.25,
    "mh_bleeding_disorders": 0.75,
    "mh_infectious_diseases": 0.75,
    "mh_allergies": 1.0,
    "mh_diabetes": 0.75,
    "mh_joint_conditions": 0.5,
    # Expectations / ICE
    "ice_ideas": 0.75,
    "ice_concerns": 0.5,
    "ice_expectations": 1.0,
    # Social history
    "soc_smoking_vaping": 1.0,
    "soc_alcohol": 1.0,
    "soc_recreational_drugs": 0.5,
    "soc_who_lives_with": 0.5,
    "soc_feel_safe": 0.5,
    "soc_support": 0.25,
    # Dietary habits
    "diet_hot_drinks_type": 1.0,
    "diet_hot_drinks_frequency": 1.0,
    "diet_hot_drinks_milk_sugar": 1.0,
    "diet_cold_drinks_type": 1.0,
    "diet_cold_drinks_frequency": 1.0,
    "diet_cold_drinks_sugar": 1.0,
    "diet_snacks_between_meals": 1.0,
    "diet_snacks_type": 0.5,
    "diet_snacks_frequency": 0.5,
    "diet_sweets_intake": 1.0,
    "diet_sweets_type": 0.5,
    # Preventive regime
    "prev_brushing_frequency": 1.0,
    "prev_brush_type": 0.75,
    "prev_brushing_times": 0.75,
    "prev_interprox_aids": 0.75,
    "prev_mouthwash_use": 0.5,
    "prev_mouthwash_type": 0.25,
    "prev_toothpaste_type": 0.5,
}

# Fixed partial marks (like Sight Test Tutor)
PHASE1_PARTIAL_MARKS = {k: round(v * 0.6, 2) for k, v in PHASE1_CRITERIA_MAX.items()}

PHASE1_ESSENTIAL = {
    "hpc_reason_for_attendance",
    "hpc_identification_of_symptoms",
    "hpc_site",
    "hpc_character",
    "mh_medications",
    "mh_allergies",
    "ice_expectations",
    "soc_smoking_vaping",
    "soc_alcohol",
    "diet_hot_drinks_type",
    "diet_cold_drinks_type",
    "diet_snacks_between_meals",
    "prev_brushing_frequency",
    "prev_toothpaste_type",
}

PHASE1_HELP = {
    "hpc_reason_for_attendance": ("HPC: reason for attendance", "State why the patient attended today."),
    "hpc_identification_of_symptoms": ("HPC: symptoms", "State the main symptom(s) in the patient’s words."),
    "hpc_site": ("HPC: site", "State where the symptoms are (tooth/quadrant/generalised)."),
    "hpc_character": ("HPC: character", "Describe the symptom quality (sharp/dull/lingering etc.)."),
    "mh_medications": ("Medical history: medications", "List medications or write “none”."),
    "mh_allergies": ("Medical history: allergies", "List allergies or write “NKDA”."),
    "ice_expectations": ("Expectations", "State what outcome the patient wants today."),
    "soc_smoking_vaping": ("Social: smoking/vaping", "Record smoking/vaping status (or ‘never’)."),
    "soc_alcohol": ("Social: alcohol", "Record alcohol intake (or ‘does not drink’)."),
    "diet_hot_drinks_type": ("Diet: hot drinks", "Type(s) of hot drinks (tea/coffee etc.)."),
    "diet_cold_drinks_type": ("Diet: cold drinks", "Type(s) of cold drinks (incl. fizzy/juice)."),
    "diet_snacks_between_meals": ("Diet: snacks", "Whether they snack between meals (yes/no)."),
    "prev_brushing_frequency": ("Prevention: brushing", "Brushing frequency (e.g. 2×/day)."),
    "prev_toothpaste_type": ("Prevention: toothpaste", "Toothpaste type (fluoride/whitening etc.)."),
}


def _sum_max(criteria_max: dict) -> float:
    return float(sum(float(v) for v in criteria_max.values()))


PHASE1_MAX_TOTAL = _sum_max(PHASE1_CRITERIA_MAX)

PHASE1_GROUPS = {
    "hpc": [
        "hpc_reason_for_attendance",
        "hpc_identification_of_symptoms",
        "hpc_site",
        "hpc_onset",
        "hpc_character",
        "hpc_progression",
        "hpc_radiation",
        "hpc_associated_symptoms",
        "hpc_timing_patterns",
        "hpc_exacerbating_relieving",
        "hpc_severity",
    ],
    "mh_ice": [
        "mh_cardiovascular",
        "mh_respiratory",
        "mh_other_systemic",
        "mh_gastrointestinal_reflux",
        "mh_genitourinary",
        "mh_medications",
        "mh_recent_hospitalisations",
        "mh_bleeding_disorders",
        "mh_infectious_diseases",
        "mh_allergies",
        "mh_diabetes",
        "mh_joint_conditions",
        "ice_ideas",
        "ice_concerns",
        "ice_expectations",
    ],
    "soc_diet_prev": [
        "soc_smoking_vaping",
        "soc_alcohol",
        "soc_recreational_drugs",
        "soc_who_lives_with",
        "soc_feel_safe",
        "soc_support",
        "diet_hot_drinks_type",
        "diet_hot_drinks_frequency",
        "diet_hot_drinks_milk_sugar",
        "diet_cold_drinks_type",
        "diet_cold_drinks_frequency",
        "diet_cold_drinks_sugar",
        "diet_snacks_between_meals",
        "diet_snacks_type",
        "diet_snacks_frequency",
        "diet_sweets_intake",
        "diet_sweets_type",
        "prev_brushing_frequency",
        "prev_brush_type",
        "prev_brushing_times",
        "prev_interprox_aids",
        "prev_mouthwash_use",
        "prev_mouthwash_type",
        "prev_toothpaste_type",
    ],
}

TEMPLATE_MARKERS = [
    "should be reported",
    "radiolucencies:",
    "radiopacities:",
    "horizontal bone levels",
    "location",
    "extension",
    "quality should",
]

FINDING_MARKERS = [
    "quality a",
    "quality u",
    "acceptable",
    "unacceptable",
    "enamel",
    "dentine",
    "d1",
    "d2",
    "pulp",
    "p",
    "normal",
    "moderate",
    "significant",
    "calculus",
    "radiolucency",
    "radiopacity",
]


def looks_like_radiograph_template(text: str) -> bool:
    t = (text or "").lower()
    if len(t.strip()) < 40:
        return False
    template_hits = sum(1 for k in TEMPLATE_MARKERS if k in t)
    finding_hits = sum(1 for k in FINDING_MARKERS if k in t)
    return template_hits >= 4 and finding_hits <= 1


def _has_any_radiograph_findings(text: str) -> bool:
    t = (text or "").lower()
    anchor_quality = any(x in t for x in ["quality a", "quality u", "acceptable", "unacceptable"])
    anchor_depth = any(x in t for x in [" d1", " d2", " enamel", " dentine", " pulp", " e ", " p "])
    anchor_bone = ("bone" in t and any(x in t for x in ["normal", "moderate", "significant", "%"]))
    anchor_calc = ("calculus" in t and any(x in t for x in ["present", "visible", "seen", "absent", "none"]))
    anchor_tooth_lesion = (re.search(r"\b(ur|ul|lr|ll)\s?\d\b", t) and ("radioluc" in t or "radiopac" in t))
    return bool(anchor_quality or anchor_depth or anchor_bone or anchor_calc or anchor_tooth_lesion)


PHASE2A_ORDER = [
    ("quality", ["quality", "acceptable", "unacceptable", " a", " u"]),
    ("radiolucencies", ["radioluc", "radiolucency", "radiolucencies", "d1", "d2", "enamel", "dentine", "pulp", "icdas", " e ", " p "]),
    ("radiopacities", ["radiopac", "radiopacity", "radiopacities"]),
    ("bone levels", ["bone", "bone level", "horizontal bone", "normal", "moderate", "significant", "%"]),
    ("calculus", ["calculus"]),
    ("justification", ["justify", "justification", "because", "reason", "indication", "should be requested"]),
]


def _phase2a_rank_gap(item: dict) -> tuple[int, int]:
    hay = " ".join([str(item.get("comment") or ""), str(item.get("expected") or "")]).lower()
    for idx, (_label, markers) in enumerate(PHASE2A_ORDER):
        if any(m in hay for m in markers):
            return (idx, 0)
    return (999, 0)


def quick_phase2a_strengths(radiograph_report: str) -> list[dict]:
    rr = (radiograph_report or "").strip()
    t = rr.lower()
    out = []

    def _quote_snip(text: str, needles: list[str], window: int = 70) -> str:
        tl = (text or "").lower()
        for needle in needles:
            i = tl.find(needle)
            if i != -1:
                start = max(0, i - 20)
                end = min(len(text), i + window)
                return text[start:end].strip()[:120]
        return ""

    if "quality" in t and any(x in t for x in [" a", " u", "acceptable", "unacceptable"]):
        out.append(
            {
                "comment": "You reported radiograph quality clearly.",
                "evidence": _quote_snip(rr, ["quality", "acceptable", "unacceptable"]),
            }
        )
    if "radioluc" in t:
        out.append(
            {
                "comment": "You described radiolucencies using radiographic language.",
                "evidence": _quote_snip(rr, ["radioluc", "d1", "d2", "enamel", "dentine"]),
            }
        )
    if "bone" in t and "level" in t and any(x in t for x in ["normal", "moderate", "significant"]):
        out.append(
            {
                "comment": "You described alveolar bone levels clearly.",
                "evidence": _quote_snip(rr, ["bone", "level", "normal", "moderate", "significant"]),
            }
        )
    return out[:3]


def _tidy_phase2a_feedback(output: dict, fields: dict) -> dict:
    tj = (fields.get("test_justification") or "").strip()
    rr = (fields.get("radiograph_report") or "").strip()
    inv = (fields.get("investigation_notes") or "").strip()
    strengths = list(output.get("strengths") or [])
    gaps = list(output.get("gaps") or [])

    # Strengths: keep short
    if not strengths:
        strengths = quick_phase2a_strengths(rr)
    strengths = strengths[:3]

    # Split gaps into must-fix vs optional
    must_fix = []
    optional = []
    for g in gaps:
        comment = (g.get("comment") or "").lower()
        expected = (g.get("expected") or "").lower()
        if any(x in comment for x in ["did not interpret", "no findings", "template", "not interpreted"]) or any(
            x in expected for x in ["write what you observed", "add observed findings", "interpretation"]
        ):
            must_fix.append(g)
        else:
            optional.append(g)

    if rr:
        if looks_like_radiograph_template(rr) or not _has_any_radiograph_findings(rr):
            must_fix.insert(
                0,
                {
                    "comment": "Radiograph report needs specific findings (not headings).",
                    "expected": (
                        "Report: quality A/U; radiolucencies with tooth + surface + depth (E/D1/D2/P); "
                        "radiopacities with tooth + extent; bone levels (normal/moderate/significant); calculus present/absent."
                    ),
                    "evidence": "",
                },
            )
    if fields.get("selected_tests") and not tj:
        must_fix.insert(
            0,
            {
                "comment": "Justification for selected tests is missing.",
                "expected": "Briefly explain why each selected investigation was chosen.",
                "evidence": "",
            },
        )

    must_fix = sorted(must_fix, key=_phase2a_rank_gap)[:4]
    optional = sorted(optional, key=_phase2a_rank_gap)

    collapsed_optional = []
    if optional:
        collapsed_optional.append(
            {
                "comment": "Further areas to consider (optional): "
                + " ".join(
                    (g.get("comment") or "").strip().rstrip(".") + "."
                    for g in optional[:4]
                    if (g.get("comment") or "").strip()
                ),
                "expected": "",
                "evidence": "",
                "optional": True,
            }
        )

    output["strengths"] = strengths
    output["gaps"] = must_fix + collapsed_optional

    if rr or inv:
        if looks_like_radiograph_template(rr) or (rr and not _has_any_radiograph_findings(rr)):
            output["summary"] = (
                "You have started documenting investigations, but the radiograph report reads like a checklist. "
                "Marks are awarded for written observations and interpretation."
            )
        else:
            output["summary"] = (
                "Marks are awarded for justified test selection plus written findings and interpretation. "
                "Focus your radiograph report on quality, lesions, bone levels and calculus."
            )
    else:
        output["summary"] = (
            "You selected investigations but did not document any interpretation or findings. "
            "Marks are awarded only for what is written in the radiograph report and investigation notes."
        )

    return output


def _tidy_phase2b_feedback(output: dict, fields: dict) -> dict:
    diagnoses = (fields.get("diagnoses") or "").strip()
    risk = (fields.get("risk_assessment") or "").strip()

    strengths = output.get("strengths") or []
    gaps = output.get("gaps") or []

    def _has_tooth_numbers(text: str) -> bool:
        return bool(re.search(r"\b(UR|UL|LR|LL)\s?\d\b", text, re.IGNORECASE))

    def _has_icdas(text: str) -> bool:
        return bool(re.search(r"\bICDAS\s*[0-6]\b|\bICDAS\b", text, re.IGNORECASE))

    def _has_gingival_statement(text: str) -> bool:
        t = text.lower()
        return any(
            x in t
            for x in (
                "gingiv",
                "gingiva",
                "gingival inflammation",
                "gingival",
                "bop",
                "bleeding on probing",
                "healthy gingiva",
                "healthy gingivae",
            )
        )

    def _has_gingival_negative(text: str) -> bool:
        return bool(
            re.search(
                r"\bno\s+(?:gingival|gingivitis|gingival\s+inflammation)\b",
                text,
                re.IGNORECASE,
            )
        )

    def _risk_linked(text: str) -> bool:
        return bool(re.search(r"\b(due to|because|linked|likely)\b", text, re.IGNORECASE))

    def _has_perio_stage(text: str) -> bool:
        return bool(re.search(r"\bstage\s*(?:i{1,3}|iv|[1-4])\b", text, re.IGNORECASE))

    def _has_perio_grade(text: str) -> bool:
        return bool(re.search(r"\bGrade\s*[A-C]\b", text, re.IGNORECASE))

    def _has_perio_extent(text: str) -> bool:
        return bool(re.search(r"\b(localised|generalised)\b", text, re.IGNORECASE))

    def _has_perio_activity(text: str) -> bool:
        return bool(re.search(r"\b(active|inactive)\b", text, re.IGNORECASE))

    def _has_perio_exacerbating(text: str) -> bool:
        return bool(re.search(r"\b(smoking|diabetes|plaque|poor oral hygiene)\b", text, re.IGNORECASE))

    def _has_tooth_wear(text: str) -> bool:
        return "tooth wear" in text.lower()

    def _has_wear_severity(text: str) -> bool:
        return bool(re.search(r"\b(mild|moderate|severe)\b", text, re.IGNORECASE))

    def _has_wear_distribution(text: str) -> bool:
        return bool(re.search(r"\b(localised|generalised)\b", text, re.IGNORECASE))

    def _has_wear_mode(text: str) -> bool:
        return bool(re.search(r"\b(erosion|erosive|attrition|abrasion|combination)\b", text, re.IGNORECASE))

    def _has_no_periodontal_disease(text: str) -> bool:
        return bool(
            re.search(
                r"\b(no\s+(?:periodontitis|periodontal\s+disease)|periodontal\s+disease\s+absent)\b",
                text,
                re.IGNORECASE,
            )
        )

    def _mentions_periodontal_disease(text: str) -> bool:
        return bool(re.search(r"\b(periodontitis|periodontal\s+disease)\b", text, re.IGNORECASE))

    def _extract_icdas_grades(text: str) -> list[int]:
        return [int(m.group(1)) for m in re.finditer(r"\bicdas\s*([0-6])\b", text, re.IGNORECASE)]

    def _has_tmj(text: str) -> bool:
        return bool(re.search(r"\bTMJ\b|\btemporomandibular\b", text, re.IGNORECASE))

    def _has_tmj_negative(text: str) -> bool:
        return bool(re.search(r"\bno\s+tmj\b|\bno\s+tmj\s+issues\b|\bno\s+tmj\s+problems\b", text, re.IGNORECASE))

    if not strengths:
        if _has_tooth_numbers(diagnoses):
            strengths.append({"comment": "You gave tooth-specific diagnoses rather than general labels.", "evidence": ""})
        if _has_icdas(diagnoses):
            strengths.append({"comment": "You used ICDAS grading to describe caries severity.", "evidence": ""})
        if _has_perio_stage(diagnoses) and _has_perio_grade(diagnoses):
            strengths.append({"comment": "Your periodontal diagnosis included stage and grade.", "evidence": ""})
        if _has_no_periodontal_disease(diagnoses):
            strengths.append({"comment": "You explicitly documented that periodontal disease was absent.", "evidence": ""})
        if _has_tmj_negative(diagnoses):
            strengths.append({"comment": "You clearly stated negative findings for TMJ.", "evidence": ""})
        if risk and _risk_linked(risk):
            strengths.append({"comment": "Your risk assessment linked risk factors to disease activity.", "evidence": ""})
    strengths = strengths[:3]

    new_gaps = []
    if not diagnoses:
        new_gaps.append(
            {
                "comment": "Diagnosis is missing — list the main diagnoses first, then supporting details.",
                "expected": "Document specific diagnoses with tooth numbers and severity where appropriate.",
                "evidence": "",
                "priority": True,
            }
        )
    else:
        if "caries" in diagnoses.lower():
            if not _has_tooth_numbers(diagnoses):
                new_gaps.append(
                    {
                        "comment": "Caries diagnosis needs tooth numbers.",
                        "expected": "Specify the affected teeth.",
                        "evidence": "",
                        "priority": True,
                    }
                )
            if not _has_icdas(diagnoses):
                new_gaps.append(
                    {
                        "comment": "Caries diagnosis needs ICDAS grading (0–6).",
                        "expected": "Include ICDAS grade for each affected tooth.",
                        "evidence": "",
                        "priority": True,
                    }
                )
            expected_icdas_grade = fields.get("expected_icdas_grade")
            provided_icdas = _extract_icdas_grades(diagnoses)
            if (
                isinstance(expected_icdas_grade, int)
                and provided_icdas
                and expected_icdas_grade not in provided_icdas
            ):
                new_gaps.append(
                    {
                        "comment": "ICDAS grade does not match expected severity for this lesion.",
                        "expected": f"ICDAS {expected_icdas_grade}",
                        "evidence": "",
                        "priority": True,
                    }
                )
        if not (_has_gingival_statement(diagnoses) or _has_gingival_negative(diagnoses)):
            new_gaps.append(
                {
                    "comment": "Gingival condition not addressed (include a negative if none).",
                    "expected": "State gingival health status (e.g. gingivitis present/absent).",
                    "evidence": "",
                    "priority": True,
                }
            )
        has_periodontal_disease = _mentions_periodontal_disease(diagnoses)
        has_no_periodontal_disease = _has_no_periodontal_disease(diagnoses)
        if has_periodontal_disease and not has_no_periodontal_disease:
            if not _has_perio_stage(diagnoses):
                new_gaps.append(
                    {
                        "comment": "Periodontal diagnosis needs staging (Stage I–IV).",
                        "expected": "Include stage.",
                        "evidence": "",
                        "priority": True,
                    }
                )
            if not _has_perio_grade(diagnoses):
                new_gaps.append(
                    {
                        "comment": "Periodontal diagnosis needs grading (Grade A–C).",
                        "expected": "Include grade.",
                        "evidence": "",
                        "priority": True,
                    }
                )
            if not _has_perio_extent(diagnoses):
                new_gaps.append(
                    {
                        "comment": "Periodontal extent (localised/generalised) was not specified.",
                        "expected": "Include extent.",
                        "evidence": "",
                        "priority": True,
                    }
                )
            if not _has_perio_activity(diagnoses):
                new_gaps.append(
                    {
                        "comment": "Periodontal activity (active/inactive) was not stated.",
                        "expected": "Include activity.",
                        "evidence": "",
                        "priority": True,
                    }
                )
            if not _has_perio_exacerbating(diagnoses):
                new_gaps.append(
                    {
                        "comment": "Exacerbating factors for periodontal disease were not recorded.",
                        "expected": "Note relevant factors (e.g., smoking, diabetes, plaque).",
                        "evidence": "",
                        "priority": True,
                    }
                )
        elif not has_no_periodontal_disease:
            new_gaps.append(
                {
                    "comment": "State explicitly if periodontal disease is absent.",
                    "expected": "Record either no periodontal disease, or provide full periodontitis staging/grading details.",
                    "evidence": "",
                    "priority": True,
                }
            )
        if _has_tooth_wear(diagnoses):
            if not _has_wear_severity(diagnoses):
                new_gaps.append(
                    {
                        "comment": "Tooth wear requires severity (mild/moderate/severe).",
                        "expected": "State severity.",
                        "evidence": "",
                        "priority": True,
                    }
                )
            if not _has_wear_distribution(diagnoses):
                new_gaps.append(
                    {
                        "comment": "Tooth wear requires distribution (localised/generalised).",
                        "expected": "State distribution.",
                        "evidence": "",
                        "priority": True,
                    }
                )
            if not _has_wear_mode(diagnoses):
                new_gaps.append(
                    {
                        "comment": "Tooth wear requires mode (erosion/attrition/abrasion/combination).",
                        "expected": "State mode.",
                        "evidence": "",
                        "priority": True,
                    }
                )
        if not _has_tmj(diagnoses):
            new_gaps.append(
                {
                    "comment": "TMJ assessment is missing (including a negative finding if absent).",
                    "expected": "State presence/absence and diagnosis if present.",
                    "evidence": "",
                    "priority": True,
                }
            )

    if not risk:
        new_gaps.append(
            {
                "comment": "Risk assessment is missing or too generic.",
                "expected": "List key risk factors and link them to likely disease activity/prognosis.",
                "evidence": "",
                "priority": True,
            }
        )
    elif not _risk_linked(risk):
        new_gaps.append(
            {
                "comment": "Risk assessment needs clearer links between risk factors and disease activity.",
                "expected": "State why each risk factor increases (or reduces) disease activity.",
                "evidence": "",
                "priority": True,
            }
        )

    new_gaps = new_gaps[:5]
    if gaps and len(new_gaps) < 5:
        for g in gaps:
            if len(new_gaps) >= 5:
                break
            new_gaps.append(g)

    gap_text = " ".join(g.get("comment", "") for g in new_gaps).lower()
    optional = []
    if _mentions_periodontal_disease(diagnoses) and not _has_no_periodontal_disease(diagnoses):
        if "activity" not in gap_text:
            optional.append("State whether periodontal disease appears active or inactive.")
        if "exacerbating" not in gap_text:
            optional.append("Record exacerbating factors (e.g. smoking, diabetes, plaque).")
    optional.append("Note protective factors as well as risks.")
    if optional:
        new_gaps.append(
            {
                "comment": " ".join(optional),
                "expected": "",
                "evidence": "",
                "optional": True,
            }
        )

    output["strengths"] = strengths
    output["gaps"] = new_gaps
    if diagnoses or risk:
        output["summary"] = (
            "Several diagnoses were identified, but key details such as grading, extent, or activity are missing. "
            "The risk assessment needs clearer links between risk factors and disease progression to support planning."
        )
    return output

def _build_phase1_marking_prompt(payload: dict, keys_subset: list[str] | None = None) -> tuple[str, str]:
    """
    Returns (system_prompt, user_content) for strict JSON marking.
    """
    canonical_keys = keys_subset or list(PHASE1_CRITERIA_MAX.keys())
    max_table = ", ".join(f"{k}={PHASE1_CRITERIA_MAX[k]}" for k in canonical_keys)
    partial_table = ", ".join(f"{k}={PHASE1_PARTIAL_MARKS[k]}" for k in canonical_keys)

    system_prompt = (
        "You are marking Phase 1 (Information Gathering) strictly from the student's notes.\n"
        "Return JSON only.\n"
        "Return a single JSON object with NO wrapper key; the top-level keys MUST be exactly the canonical keys.\n\n"
        "Rules:\n"
        "- Award marks ONLY when the student wrote evidence for that criterion.\n"
        "- Evidence MUST be an exact verbatim substring from the student's notes (not paraphrase).\n"
        "- Do NOT infer or assume negatives.\n"
        "- If unclear/vague, use status='partial'.\n"
        "- If absent, status='missing'.\n\n"
        "Consistency contract:\n"
        f"- CRITERIA_MAX: {max_table}\n"
        f"- PARTIAL_MARKS: {partial_table}\n"
        "- You MUST set marks numerically as:\n"
        "  status='accurate' -> mark = CRITERIA_MAX[key]\n"
        "  status='partial'  -> mark = PARTIAL_MARKS[key]\n"
        "  status in {'missing'} -> mark = 0\n"
        "- Use ONLY the student's notes; do not rely on clinical common sense.\n"
        "- Do not use selected_tests as evidence.\n"
    )

    user_content = (
        "Student Phase 1 fields (ONLY source of truth):\n"
        f"{json.dumps(payload, ensure_ascii=False, indent=2)}\n\n"
        "Return JSON with ONLY these canonical keys:\n"
        f"{canonical_keys}\n\n"
        "Each value must be:\n"
        '{ "mark": <number>, "evidence": "<verbatim substring or empty>", "status": '
        '"accurate" | "partial" | "missing" }\n'
    )

    return system_prompt, user_content


def _call_openai_json(system_prompt: str, user_content: str, max_tokens: int = 900) -> dict:
    kwargs = {
        "model": PREFERRED_MODEL,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content},
        ],
        "temperature": 0.0,
        "response_format": {"type": "json_object"},
        "max_completion_tokens": max_tokens,
    }
    try:
        try:
            resp = client.with_options(timeout=60).chat.completions.create(**kwargs)
        except AttributeError:
            resp = client.chat.completions.create(**kwargs, timeout=60)
    except TypeError:
        # Older SDKs may require max_tokens instead of max_completion_tokens.
        kwargs.pop("max_completion_tokens", None)
        kwargs["max_tokens"] = max_tokens
        try:
            resp = client.with_options(timeout=60).chat.completions.create(**kwargs)
        except AttributeError:
            resp = client.chat.completions.create(**kwargs, timeout=60)
    msg = resp.choices[0].message
    content = msg.content
    if isinstance(content, list):
        if content and hasattr(content[0], "text"):
            raw = content[0].text or ""
        elif content and isinstance(content[0], dict) and "text" in content[0]:
            raw = content[0]["text"] or ""
        else:
            raw = ""
    else:
        raw = content or ""
    return json.loads(raw) if raw else {}


def _bucketize_marks(marks_norm: dict, order: list[str] | None = None) -> tuple[list, list, list]:
    accurate, partial, missing = [], [], []
    keys = list(marks_norm.keys())
    if order:
        idx = {k: i for i, k in enumerate(order)}
        keys.sort(key=lambda k: (idx.get(k, 10_000), k))
    else:
        keys.sort()
    for k in keys:
        v = marks_norm.get(k) or {}
        st = (v.get("status") or "").lower()
        if st == "accurate":
            accurate.append(k)
        elif st == "partial":
            partial.append(k)
        else:
            missing.append(k)
    return accurate, partial, missing


def _render_phase1_feedback_from_marks(marks_norm: dict) -> dict:
    essential_order = [
        "hpc_reason_for_attendance",
        "hpc_identification_of_symptoms",
        "hpc_site",
        "hpc_character",
        "mh_medications",
        "mh_allergies",
        "ice_expectations",
        "soc_smoking_vaping",
        "soc_alcohol",
        "diet_hot_drinks_type",
        "diet_cold_drinks_type",
        "diet_snacks_between_meals",
        "prev_brushing_frequency",
        "prev_toothpaste_type",
    ]
    accurate, partial, missing = _bucketize_marks(marks_norm, order=essential_order)

    strengths = []
    gaps = []

    section_names = {
        "hpc": "History of presenting complaint",
        "mh": "Medical history",
        "ice": "Expectations (ICE)",
        "soc": "Social history",
        "diet": "Diet",
        "prev": "Preventive regime",
    }

    section_strengths = {
        "hpc": [
            "You recorded the main complaint and at least one trigger.",
            "You described the nature of the pain/sensitivity.",
        ],
        "mh": [
            "You documented relevant medical history items.",
        ],
        "ice": [
            "You recorded what the patient is hoping for today.",
        ],
        "soc": [
            "You documented smoking status.",
        ],
        "diet": [
            "You recorded at least one dietary exposure.",
        ],
        "prev": [
            "You recorded brushing behaviour.",
        ],
    }

    section_fix = {
        "hpc": [
            "Record where the symptoms are (single tooth / quadrant / generalised).",
            "Record onset and progression (when it started, whether worsening).",
            "Add severity (e.g., 5/10) and what makes it better/worse.",
        ],
        "mh": [
            "Document medications (or 'no medications').",
            "Document allergies (or 'no known allergies').",
            "Record key systems explicitly (cardiac, respiratory, bleeding risk, diabetes).",
        ],
        "ice": [
            "Document the patient’s concerns (e.g., worries about fillings / root canal).",
            "Document patient ideas/beliefs where relevant.",
        ],
        "soc": [
            "Record alcohol intake (or 'does not drink').",
            "Record recreational drug use (or 'none').",
        ],
        "diet": [
            "Record hot drinks: type + frequency + sugar/milk.",
            "Record cold drinks: type + frequency + sugar exposure.",
            "Record snacking between meals (type + frequency).",
            "Record sweets intake (even sugar-free).",
        ],
        "prev": [
            "Record brushing frequency and time of day.",
            "Record brush type (manual / electric).",
            "Record interdental cleaning.",
            "Record toothpaste type (fluoride / whitening/abrasive etc.).",
        ],
    }

    section_optional = {
        "hpc": [
            "Consider associated symptoms and whether pain radiates.",
        ],
        "mh": [
            "If a condition is present, note whether it is stable/well-controlled.",
        ],
        "ice": [
            "Add what the patient expects from the longer-term plan.",
        ],
        "soc": [
            "Consider living situation / safety / support network where relevant.",
        ],
        "diet": [
            "If high-risk exposure is present, note timing/frequency (grazing vs meals).",
        ],
        "prev": [
            "Record mouthwash use and type.",
        ],
    }

    def _section_key(k: str) -> str:
        return k.split("_", 1)[0]

    missing_essential = [k for k in missing if k in PHASE1_ESSENTIAL]
    missing_other = [k for k in missing if k not in PHASE1_ESSENTIAL]

    def _has_any(keys: list[str], prefix: str) -> bool:
        return any(k.startswith(prefix + "_") for k in keys)

    MAX_PRIORITY = 3
    MAX_REFINE = 3

    # Strengths (short, supportive)
    if any(k.startswith("hpc_") for k in (accurate + partial)):
        strengths.append({"comment": "You recorded relevant details of the presenting complaint.", "evidence": ""})
    if any(k.startswith("mh_") for k in (accurate + partial)):
        strengths.append({"comment": "You recorded relevant points from the medical history.", "evidence": ""})
    if any(k.startswith("diet_") for k in (accurate + partial)):
        strengths.append({"comment": "You documented dietary factors relevant to caries risk.", "evidence": ""})
    strengths = strengths[:3]

    # Priority gaps: missing essentials only (max 3) in stable order.
    missing_essential_sorted = [k for k in essential_order if k in missing_essential]
    for k in missing_essential_sorted[:MAX_PRIORITY]:
        label, expected = PHASE1_HELP.get(k, (k.replace("_", " "), "Document this explicitly in your notes."))
        gaps.append(
            {
                "comment": f"Fix before moving on: {label}.",
                "expected": expected,
                "evidence": "",
                "priority": True,
            }
        )

    # Refinements: partials (max 3), essentials first.
    partial_keys = [k for k, v in marks_norm.items() if v.get("status") == "partial"]
    partial_priority = [k for k in partial_keys if k in PHASE1_ESSENTIAL]
    partial_other = [k for k in partial_keys if k not in PHASE1_ESSENTIAL]
    partial_sorted = partial_priority + partial_other
    for k in partial_sorted[:MAX_REFINE]:
        label, _ = PHASE1_HELP.get(k, (k.replace("_", " "), ""))
        gaps.append(
            {
                "comment": f"Refine: {label} is mentioned but incomplete.",
                "expected": "Add one more specific detail so this is chairside-complete.",
                "evidence": "",
                "refine": True,
            }
        )

    # Optional: single short line.
    missing_other = [
        k for k, v in marks_norm.items()
        if v.get("status") == "missing" and k not in PHASE1_ESSENTIAL
    ]
    if missing_other:
        optional_prompts = []
        if any(k.startswith("hpc_") for k in missing_other):
            optional_prompts.append("HPC: consider onset/progression/severity and relieving factors if relevant.")
        if any(k.startswith("mh_") for k in missing_other):
            optional_prompts.append("Medical history: consider key systems (e.g., bleeding risk/diabetes) if relevant.")
        if any(k.startswith("soc_") for k in missing_other):
            optional_prompts.append("Social: consider support/safety where clinically relevant.")
        if any(k.startswith("diet_") for k in missing_other):
            optional_prompts.append("Diet: consider frequency/timing of sugar exposures (grazing vs meals).")
        if any(k.startswith("prev_") for k in missing_other):
            optional_prompts.append("Prevention: consider interdental cleaning/mouthwash if relevant.")
        gaps.append(
            {
                "comment": "Optional improvements: " + " ".join(optional_prompts[:3]),
                "expected": "",
                "evidence": "",
                "optional": True,
            }
        )

    summary = (
        "Address the priority items above before moving on to investigations."
        if missing_essential_sorted
        else "Core Phase 1 information is present. You can move on, and refine later if needed."
    )

    return {
        "strengths": strengths,
        "gaps": gaps,
        "unsafe_or_concerning": [],
        "summary": summary,
    }


def _compute_score_0_to_10(total_marks: float, max_total: float) -> float:
    if max_total <= 0:
        return 0.0
    return round(10.0 * float(total_marks) / float(max_total), 1)


def generate_feedback_for_session_phase(
    session,
    phase: int,
    scope: str | None = None,
    case_payload: dict | None = None,
) -> tuple[dict, dict]:
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
                "test_justification": session.test_justification,
                "radiograph_report": session.radiograph_report,
                "investigation_notes": session.investigation_notes,
            }
            phase_name = "PHASE 2A – INVESTIGATIONS & REPORT"
        elif scope == "diagnosis":
            fields = {
                "diagnoses": session.diagnoses,
                "risk_assessment": session.risk_assessment,
            }
            if isinstance(case_payload, dict):
                truth = case_payload.get("diagnosis_truth")
                if isinstance(truth, list):
                    for item in truth:
                        if not isinstance(item, str):
                            continue
                        m = re.search(r"\bICDAS\s*([0-6])\b", item, re.IGNORECASE)
                        if m:
                            fields["expected_icdas_grade"] = int(m.group(1))
                            break
            phase_name = "PHASE 2B – DIAGNOSIS & RISK ASSESSMENT"
        else:
            fields = {
                "selected_tests": session.selected_tests or [],
                "test_justification": session.test_justification,
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
                            "comment": "Tests were selected, but no findings were documented.",
                            "expected": "Selecting a test is not assessed — interpretation is. Write a radiograph report and/or investigation notes.",
                            "evidence": "",
                        }
                    ],
                    "unsafe_or_concerning": [],
                    "summary": (
                        "You selected investigations but did not document any interpretation or findings. "
                        "Marks are awarded only for what is written in the radiograph report and investigation notes."
                    ),
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
        normalized = normalized.replace("•", "-")
        normalized = normalized.replace("–", "-").replace("—", "-")
        normalized = re.sub(r"\s+", " ", normalized).strip()
        return normalized

    def _evidence_present(evidence: str, student_text: str) -> bool:
        if not evidence:
            return False
        return _norm_text(evidence) in _norm_text(student_text)

    # --- NEW: strict criterion-level marking for Phase 1 ---
    if phase == 1 and os.getenv("ORAL_STRICT_PHASE1", "1") == "1":
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
        student_text = _all_student_text(payload)

        parsed_marks = {}
        last_err = None
        for group_name, keys_subset in PHASE1_GROUPS.items():
            system_prompt, user_content = _build_phase1_marking_prompt(payload, keys_subset)
            for max_tokens in (1400, 900):
                try:
                    part = _call_openai_json(system_prompt, user_content, max_tokens=max_tokens)
                    if isinstance(part, dict):
                        for wrapper in ("marks", "results", "criteria", "data"):
                            if wrapper in part and isinstance(part[wrapper], dict):
                                part = part[wrapper]
                                break
                        if isinstance(part, dict):
                            parsed_marks.update(part)
                    break
                except Exception as exc:
                    last_err = exc
                    continue

        if not parsed_marks:
            logger.exception(
                "Strict Phase 1 marking failed; falling back to narrative scorer.",
                exc_info=last_err,
            )
            if os.getenv("ORAL_STRICT_PHASE1_RAISE", "0") == "1":
                raise

        logger.info("STRICT PHASE1 keys: %s", list(parsed_marks.keys())[:10])

        # Validate + clamp + enforce evidence-in-student-notes
        marks_norm = {}
        earned = 0.0
        for key, maxv in PHASE1_CRITERIA_MAX.items():
            entry = parsed_marks.get(key) if isinstance(parsed_marks, dict) else None
            entry = entry if isinstance(entry, dict) else {}
            status = (entry.get("status") or "").strip().lower()
            ev = (entry.get("evidence") or "").strip()

            # Enforce verbatim evidence
            if ev and not _evidence_present(ev, student_text):
                status = "missing"
                ev = ""

            if status == "accurate":
                m = float(maxv)
            elif status == "partial":
                m = float(PHASE1_PARTIAL_MARKS.get(key, 0.0))
                m = min(m, float(maxv))
            else:
                status = "missing"
                m = 0.0
                ev = ""

            marks_norm[key] = {"mark": m, "evidence": ev[:240], "status": status}
            earned += m

        # Build deterministic feedback lists from marks
        output = _render_phase1_feedback_from_marks(marks_norm)

        # Compute 0–10 score locally
        score_float = _compute_score_0_to_10(earned, PHASE1_MAX_TOTAL)
        score_val = int(round(score_float))

        # Keep your existing "missing required sections => cap 4" rule
        missing_sections = [k for k, v in fields.items() if isinstance(v, str) and not v.strip()]
        if missing_sections:
            score_val = min(score_val, 4)

        missing_essential_count = sum(
            1 for k in PHASE1_ESSENTIAL if marks_norm.get(k, {}).get("status") == "missing"
        )
        missing_total_count = sum(
            1 for v in marks_norm.values() if v.get("status") == "missing"
        )
        partial_count = sum(
            1 for v in marks_norm.values() if v.get("status") == "partial"
        )
        core_sections_empty_count = 0
        for k in (
            "hpc_notes",
            "medical_history_notes",
            "expectations_notes",
            "social_history_notes",
            "diet_notes",
            "preventive_regime_notes",
        ):
            val = fields.get(k)
            if not (isinstance(val, str) and len(val.strip()) >= 5):
                core_sections_empty_count += 1
        score_val = max(0, min(10, score_val))
        return output, {
            "score": score_val,
            "score_raw": score_float,
            "missing_essential_count": missing_essential_count,
            "missing_total_count": missing_total_count,
            "partial_count": partial_count,
            "core_sections_empty_count": core_sections_empty_count,
        }
    if phase == 2 and scope == "investigations":
        rr = (fields.get("radiograph_report") or "").strip()
        if rr and looks_like_radiograph_template(rr) and not _has_any_radiograph_findings(rr):
            return (
                {
                    "strengths": [],
                    "gaps": [
                        {
                            "comment": "You have written a radiograph reporting template rather than radiographic findings.",
                            "expected": (
                                "Write what you observed (e.g., quality A/U; radiolucencies with tooth + surface + depth; "
                                "bone levels normal/moderate/significant; calculus present/absent)."
                            ),
                            "evidence": "",
                        }
                    ],
                    "unsafe_or_concerning": [],
                    "summary": (
                        "A checklist of headings is not interpreted evidence. "
                        "Marks are awarded only for documented observations."
                    ),
                },
                {"score": 1},
            )
    phase1_rules = ""
    phase2_rules = ""
    summary_focus = ""
    if phase == 1:
        phase1_rules = """
PHASE 1 MARKING RULES (STRICT):
- Phase 1 assesses structured information gathering.
- The following sections are REQUIRED for a satisfactory attempt:
  • History of presenting complaint
  • Medical history
  • Expectations of treatment and outcome
  • Social history
  • Dietary habits
  • Current preventive regime
- If one or more required sections are missing or empty:
  • The maximum score MUST NOT exceed 4/10.
  • Missing sections MUST be listed explicitly in gaps.
- Depth in a single section does NOT compensate for missing sections.
- For "Current preventive regime", only credit oral health prevention behaviours
  (e.g., brushing frequency, fluoride toothpaste, interdental cleaning, mouthwash, dental attendance).
  Do NOT credit generic lifestyle or motivation statements as preventive regime.
"""
    if phase == 2 and scope == "investigations":
        phase2_rules = """
PHASE 2A MARKING RULES (INVESTIGATIONS & RADIOGRAPH REPORT):
- Selecting investigations alone does NOT demonstrate competence.
- Credit is awarded for both:
  • clear justification for selected tests
  • documented findings and interpretation
- Listing headings or prompts (e.g. “radiolucencies: location”) without findings
  counts as a reporting template and earns no interpretation credit.
- Generic test justification (e.g. “BPE should always be requested”) is acceptable and should not be penalised.
  Marks in this phase mainly come from reporting/interpretation of findings.
- If investigations are selected but no findings are documented:
  • The maximum score MUST NOT exceed 3/10.
- Evidence must come ONLY from:
  • test_justification
  • radiograph_report
  • investigation_notes
  (selected_tests must NOT be used as evidence).
- If radiograph_report contains text:
  • You MUST comment on it (as a strength or a gap).
  • Use a direct quote from the student’s text as evidence where possible.
- If the radiograph report cannot be interpreted,
  this MUST be explained clearly in the summary.
"""
        summary_focus = "Summary must focus on interpretation quality."
    elif phase == 2 and scope == "diagnosis":
        phase2_rules = """
PHASE 2B MARKING RULES (DIAGNOSIS & RISK):
- Grade ONLY what the student explicitly wrote.
- Do NOT infer diagnoses from earlier phases or investigations.
- If something is not written, treat it as not assessed or not reported.
- Each diagnosis stream must be addressed explicitly:
  • Caries (teeth + ICDAS grade)
  • Gingival conditions
  • Periodontal status:
    - if periodontitis present: include stage, grade, extent, activity, exacerbating factors
    - if absent: explicitly state no periodontal disease / no periodontitis
  • Tooth wear (severity, distribution, mode)
  • Temporomandibular joint
- Vague or incomplete diagnoses must be marked as partial or missing.
- Negative findings (e.g. “no TMJ issues”) are valid and should be credited.
- Evidence must be a direct verbatim quote from the student’s text.
- Risk assessment must:
  • Identify relevant risk factors
  • Link them to disease activity or prognosis
- If risk assessment is missing or generic:
  • Maximum score MUST NOT exceed 4/10.
"""
        summary_focus = "Summary must focus on diagnostic reasoning and risk assessment."

    summary_focus_line = f" {summary_focus}" if summary_focus else ""

    prompt = f"""
You are an experienced oral health educator marking a dental student.

IMPORTANT RULES (do not break these):
- Grade ONLY what the student explicitly wrote in the fields below.
- Do NOT infer actions or knowledge that are not written.
- If the student did not write something, treat it as not done.
- Every positive claim MUST include a direct quote from the student's free-text as evidence.
- Evidence must be a verbatim substring from the student's free-text fields. Do NOT use selected_tests as evidence.
{phase1_rules}{phase2_rules}

{phase_name}
STUDENT FIELDS:
{json.dumps(payload, ensure_ascii=False, indent=2)}

Return ONLY JSON in this schema:
{{
  "feedback": {{
    "strengths": [{{"comment":"...","evidence":"DIRECT QUOTE"}}],
    "gaps": [{{"comment":"...","expected":"...","evidence":""}}],
    "unsafe_or_concerning": [{{"comment":"...","evidence":"DIRECT QUOTE (or empty if none)"}}],
    "summary": "1-2 sentences. No praise without evidence.{summary_focus_line}"
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
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.2,
            response_format={"type": "json_object"},
            max_completion_tokens=900,
        )
        raw = _extract_content(resp)
        parsed = json.loads(raw)
    except Exception as e:
        logger.exception(
            "AI phase feedback failed. phase=%s scope=%s model=%r raw_preview=%r",
            phase,
            scope,
            PREFERRED_MODEL,
            (raw[:500] if isinstance(raw, str) else raw),
        )
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
    strengths_clean = []
    for it in output["strengths"] or []:
        it = _ensure_item_dict(it, ("comment", "evidence", "expected"))
        evidence = (it.get("evidence") or "").strip()[:240]
        if evidence and _evidence_present(evidence, student_text):
            it["evidence"] = evidence
        else:
            it["evidence"] = ""
        strengths_clean.append(it)
    output["strengths"] = strengths_clean
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
    if phase == 2 and scope == "investigations":
        output = _tidy_phase2a_feedback(output, fields)
    if phase == 2 and scope == "diagnosis":
        output = _tidy_phase2b_feedback(output, fields)

    try:
        score_val = int(round(float(score)))
    except Exception:
        score_val = 0
    if phase == 1:
        missing = [
            k for k, v in fields.items()
            if isinstance(v, str) and not v.strip()
        ]
        if missing:
            score_val = min(score_val, 4)
    if phase == 2 and scope == "investigations":
        if fields.get("selected_tests") and not (
            (fields.get("radiograph_report") or "").strip()
            or (fields.get("investigation_notes") or "").strip()
        ):
            logging.getLogger(__name__).info(
                "Phase2A cap applied: tests selected without interpretation."
            )
            score_val = min(score_val, 3)
    if phase == 2 and scope == "diagnosis":
        if not (fields.get("risk_assessment") or "").strip():
            logging.getLogger(__name__).info(
                "Phase2B cap applied: missing risk assessment."
            )
            score_val = min(score_val, 4)
    score_val = max(0, min(10, score_val))
    return output, {"score": score_val}


def generate_feedback_for_session(session, case_payload: dict | None = None) -> tuple[dict, dict, float]:
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
        "test_justification": session.test_justification,
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

    # Charlotte calibration: treat incorrect ICDAS grade as a diagnostic gap (not unsafe).
    if isinstance(case_payload, dict):
        expected_icdas_grade = None
        truth = case_payload.get("diagnosis_truth")
        if isinstance(truth, list):
            for item in truth:
                if not isinstance(item, str):
                    continue
                m = re.search(r"\bICDAS\s*([0-6])\b", item, re.IGNORECASE)
                if m:
                    expected_icdas_grade = int(m.group(1))
                    break
        diagnoses_text = (data.get("diagnoses") or "")
        provided_icdas = [
            int(m.group(1))
            for m in re.finditer(r"\bicdas\s*([0-6])\b", diagnoses_text, re.IGNORECASE)
        ]
        if (
            isinstance(expected_icdas_grade, int)
            and provided_icdas
            and expected_icdas_grade not in provided_icdas
        ):
            feedback["investigations_and_diagnosis"]["gaps"].append(
                {
                    "comment": "ICDAS grade does not match expected severity for this lesion.",
                    "expected": f"ICDAS {expected_icdas_grade}",
                    "evidence": "",
                }
            )

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
        normalized = normalized.replace("•", "-")
        normalized = normalized.replace("–", "-").replace("—", "-")
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

    def _score_text(val) -> str:
        try:
            return f"{float(val):.1f}/10"
        except Exception:
            return "0.0/10"

    h_score = scores.get("history_and_information", 0)
    i_score = scores.get("investigations_and_diagnosis", 0)
    p_score = scores.get("planning_and_consent", 0)

    score_line = (
        f"Section scores: History {_score_text(h_score)}, "
        f"Investigations & diagnosis {_score_text(i_score)}, "
        f"Planning {_score_text(p_score)}."
    )

    if float(overall or 0.0) >= 7.0:
        tone_line = (
            "Overall this is a solid submission; keep refining precision and linkage between findings, diagnosis, and planning."
        )
    elif float(overall or 0.0) >= 4.0:
        tone_line = (
            "Overall this is a developing submission with clear progress, but key details remain incomplete."
        )
    else:
        tone_line = (
            "Overall this submission is incomplete and needs fuller documentation across sections."
        )

    if total_strengths == 0:
        tone_line += " Few evidenced strengths were detected in the written text."

    feedback["overall_summary"] = f"{score_line} {tone_line}"
    overall = round(float(overall or 0.0), 2)
    scores["overall"] = overall

    return feedback, scores, overall
