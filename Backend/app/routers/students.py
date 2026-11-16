"""
Student identity record endpoints (admin/issuer only).

Section 1 of the brief: "A student gets one identity, and that identity
can be used across services." This router owns that identity record,
including the RFID card UID the gate hardware uses to find it.
"""
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app import models, schemas
from app.database import get_db
from app.security import require_admin

router = APIRouter(prefix="/students", tags=["students"], dependencies=[Depends(require_admin)])


def _normalize_uid(uid: str | None) -> str | None:
    """Card UIDs are stored uppercase hex with no separators, matching what
    the ESP32 firmware sends (e.g. "01020304")."""
    if uid is None:
        return None
    cleaned = uid.replace(":", "").replace(" ", "").strip().upper()
    return cleaned or None


@router.post("", response_model=schemas.StudentOut, status_code=status.HTTP_201_CREATED)
def create_student(payload: schemas.StudentCreate, db: Session = Depends(get_db)):
    data = payload.model_dump()
    data["rfid_uid"] = _normalize_uid(data.get("rfid_uid"))
    student = models.Student(**data)
    db.add(student)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A student with this student_id, email or RFID card already exists",
        )
    db.refresh(student)
    return student


@router.get("", response_model=list[schemas.StudentOut])
def list_students(db: Session = Depends(get_db)):
    return db.query(models.Student).order_by(models.Student.created_at.desc()).all()


@router.get("/{student_id}", response_model=schemas.StudentOut)
def get_student(student_id: str, db: Session = Depends(get_db)):
    student = (
        db.query(models.Student)
        .filter(models.Student.student_id == student_id)
        .first()
    )
    if not student:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Student not found")
    return student


@router.patch("/{student_id}/rfid", response_model=schemas.StudentOut)
def assign_rfid(student_id: str, payload: schemas.StudentRfidUpdate, db: Session = Depends(get_db)):
    """Assign or change the RFID card UID for a student."""
    student = (
        db.query(models.Student)
        .filter(models.Student.student_id == student_id)
        .first()
    )
    if not student:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Student not found")

    student.rfid_uid = _normalize_uid(payload.rfid_uid)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="That RFID card is already assigned to another student",
        )
    db.refresh(student)
    return student
