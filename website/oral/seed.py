"""
Utility to create oral tables and seed a starter case.
Run: python -m website.oral.seed
"""
from website.oral.db import engine
from website.oral.models import Base, Case


def ensure_tables():
    Base.metadata.create_all(engine)


def seed_sample_case():
    from website.oral.db import SessionLocal

    db = SessionLocal()
    try:
        # Ensure only Charlotte remains active; deactivate any other cases.
        db.query(Case).filter(Case.case_code != "charlotte").update(
            {"is_active": 0}, synchronize_session=False
        )

        existing = db.query(Case).filter(Case.case_code == "charlotte").first()
        if not existing:
            db.add(
                Case(
                    case_code="charlotte",
                    title="Charlotte – cold/sweet sensitivity",
                    short_description=(
                        "Active adult with cold/sweet sensitivity, TMJ click, dietary acid/sugar exposures; build history and plan."
                    ),
                    is_active=1,
                )
            )
        else:
            existing.is_active = 1

        db.commit()
    finally:
        db.close()


def main():
    ensure_tables()
    seed_sample_case()
    print("✅ Oral tables ready; sample case seeded (oral-001).")


if __name__ == "__main__":
    main()
