"""
Pydantic request/response models.

Kept separate from ORM models on purpose: schemas control exactly what
crosses the API boundary, which matters most for the public /verify
endpoint (must never leak private student fields -- section 7 of the brief).
"""
from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr

from app.models import CredentialStatus, VerificationResult

# ---------- Students ----------


class StudentCreate(BaseModel):
    student_id: str
    full_name: str
    email: EmailStr
    phone: str | None = None
    course: str | None = None
    hostel: str | None = None


class StudentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    student_id: str
    full_name: str
    email: EmailStr
    phone: str | None
    course: str | None
    hostel: str | None
    created_at: datetime


# ---------- Credentials ----------


class CredentialCreate(BaseModel):
    student_id: str  # the human-readable student_id (e.g. college roll no.), not the internal UUID
    credential_type: str
    title: str
    issued_by: str


class CredentialOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    student_id: str
    credential_type: str
    title: str
    issued_by: str
    proof_hash: str
    status: CredentialStatus
    issued_at: datetime
    revoked_at: datetime | None


# ---------- Verification (public-facing; no private student fields) ----------


class VerificationOut(BaseModel):
    result: VerificationResult
    credential_type: str | None = None
    title: str | None = None
    issued_by: str | None = None
    issued_at: datetime | None = None
    proof_hash: str
    checked_at: datetime


class VerificationLogOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    credential_id: str | None
    proof_hash_checked: str
    result: VerificationResult
    verifier_note: str | None
    checked_at: datetime
