"""
Seeds the three test students that were previously hardcoded in the ESP32
firmware, so your existing physical cards keep working.

Run from the Backend/ folder (with your venv active and Postgres up):

    python -m scripts.seed_students

Safe to run more than once -- existing students are left untouched.
The email addresses are placeholders; edit them later if you care.
"""
from app.database import Base, SessionLocal, engine
from app import models

SEED = [
    {"student_id": "ATLAS001", "full_name": "Rishit Rebant",   "email": "rishit.rebant.24cse@bmu.edu.in", "rfid_uid": "01020304"},
    {"student_id": "ATLAS002", "full_name": "Gauri Pandey", "email": "gauri.pandey.24cse@bmu.edu.in", "rfid_uid": "11223344"},
    {"student_id": "ATLAS003", "full_name": "Prernaa Bhargava", "email": "prernaa.bhargava.24cse@bmu.edu.in", "rfid_uid": "55667788"},
]


def main() -> None:
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        for row in SEED:
            exists = (
                db.query(models.Student)
                .filter(models.Student.student_id == row["student_id"])
                .first()
            )
            if exists:
                print(f"skip   {row['student_id']} (already exists)")
                continue
            db.add(models.Student(**row))
            print(f"create {row['student_id']}  uid={row['rfid_uid']}")
        db.commit()
    finally:
        db.close()


if __name__ == "__main__":
    main()
