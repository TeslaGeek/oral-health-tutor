import json
from pathlib import Path

# Base directory for the website package; cases are stored in website/cases
BASE_DIR = Path(__file__).resolve().parent.parent
CASES_DIR = BASE_DIR / "cases"


def load_case(case_id: str) -> dict:
    """
    Load a patient case JSON by id (e.g. 'charlotte').
    """
    case_path = CASES_DIR / f"{case_id}.json"
    if not case_path.exists():
        raise FileNotFoundError(f"Case file not found: {case_path}")

    with open(case_path, "r", encoding="utf-8") as f:
        return json.load(f)
