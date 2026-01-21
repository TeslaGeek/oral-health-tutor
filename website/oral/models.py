from sqlalchemy import (
    Column, Integer, BigInteger, String, Text, JSON, Enum,
    ForeignKey, TIMESTAMP, DECIMAL, Boolean
)
from sqlalchemy.orm import declarative_base
from sqlalchemy.ext.mutable import MutableList, MutableDict
import enum

Base = declarative_base()


class Case(Base):
    __tablename__ = "oral_cases"

    id = Column(Integer, primary_key=True)
    case_code = Column(String(50), unique=True, nullable=False)
    title = Column(String(255), nullable=False)
    short_description = Column(Text)
    is_active = Column(Integer, default=1)
    # created_at / updated_at exist in the DB, but we don't need them in the model yet


class SessionStatus(str, enum.Enum):
    IN_PROGRESS = "in_progress"
    SUBMITTED = "submitted"
    MARKED = "marked"


class Session(Base):
    __tablename__ = "oral_sessions"

    id = Column(BigInteger, primary_key=True)

    student_identifier = Column(String(100), nullable=False)
    case_id = Column(Integer, ForeignKey("oral_cases.id"), nullable=False)
    attempt_number = Column(Integer, default=1)

    started_at = Column(TIMESTAMP)
    completed_at = Column(TIMESTAMP)

    # Phase 1
    hpc_notes = Column(Text)
    medical_history_notes = Column(Text)
    expectations_notes = Column(Text)
    social_history_notes = Column(Text)
    diet_notes = Column(Text)
    preventive_regime_notes = Column(Text)

    # Phase 2
    selected_tests = Column(MutableList.as_mutable(JSON), default=list)
    radiograph_report = Column(Text)
    investigation_notes = Column(Text)
    diagnoses = Column(Text)
    risk_assessment = Column(Text)
    phase2_investigations_locked = Column(Boolean, nullable=False, default=False)
    phase1_completed_at = Column(TIMESTAMP)
    phase2_completed_at = Column(TIMESTAMP)

    # Phase 3
    prevention_plan = Column(Text)
    rehab_options = Column(Text)
    operative_options = Column(Text)
    patient_preferences = Column(Text)
    final_plan_and_consent_notes = Column(Text)
    phase3_completed_at = Column(TIMESTAMP)

    # Feedback
    section_scores_json = Column(MutableDict.as_mutable(JSON), default=dict)
    overall_score = Column(DECIMAL(4, 2))
    feedback_json = Column(MutableDict.as_mutable(JSON), default=dict)
    chat_log = Column(MutableList.as_mutable(JSON), default=list)

    status = Column(
        Enum(SessionStatus),
        default=SessionStatus.IN_PROGRESS,
        nullable=False
    )
