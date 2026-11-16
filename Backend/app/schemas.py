"""
Pydantic request/response models.

Kept separate from ORM models on purpose: schemas control exactly what
crosses the API boundary, which matters most for the public /verify
endpoint (must never leak private student fields -- section 7 of the brief).
"""
from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr

from app.models import ChainTxStatus, CredentialStatus, GateDirection, VerificationResult

# ---------- Students ----------


class StudentCreate(BaseModel):
    student_id: str
    full_name: str
    email: EmailStr
    phone: str | None = None
    course: str | None = None
    hostel: str | None = None
    rfid_uid: str | None = None


class StudentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    student_id: str
    full_name: str
    email: EmailStr
    phone: str | None
    course: str | None
    hostel: str | None
    rfid_uid: str | None
    inside: bool
    created_at: datetime


class StudentRfidUpdate(BaseModel):
    rfid_uid: str


# ---------- Credentials ----------


class CredentialCreate(BaseModel):
    student_id: str  # the human-readable student_id (e.g. college roll no.), not the internal UUID
    credential_type: str
    title: str
    issued_by: str


class ChainStatusOut(BaseModel):
    """Embedded on credential/gate-log responses so callers can see whether
    the on-chain write has landed yet, without a separate request."""

    tx_hash: str | None = None
    status: ChainTxStatus | None = None
    error: str | None = None


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
    chain: ChainStatusOut | None = None


# ---------- Verification (public-facing; no private student fields) ----------


class VerificationOut(BaseModel):
    result: VerificationResult
    credential_type: str | None = None
    title: str | None = None
    issued_by: str | None = None
    issued_at: datetime | None = None
    proof_hash: str
    checked_at: datetime

    # Phase 2: what the blockchain itself says about this proof, read live
    # at verification time -- independent of the database row above. If
    # these ever disagree with the database fields, that's worth flagging:
    # the chain is the tamper-evident copy.
    on_chain: bool = False
    on_chain_revoked: bool | None = None
    chain_error: str | None = None


class VerificationLogOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    credential_id: str | None
    proof_hash_checked: str
    result: VerificationResult
    verifier_note: str | None
    checked_at: datetime


# ---------- Gate (Phase 2 hardware integration) ----------


class GateScanRequest(BaseModel):
    uid: str
    direction: GateDirection


class GateScanOut(BaseModel):
    granted: bool
    reason: str
    message: str
    student_name: str | None = None
    student_id: str | None = None
    proof_hash: str | None = None


class GateLogOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    student_id: str | None
    rfid_uid_scanned: str
    direction: GateDirection
    granted: bool
    reason: str
    proof_hash: str | None
    occurred_at: datetime
    chain: ChainStatusOut | None = None


class GateStatusOut(BaseModel):
    """One row per student, for the frontend's live inside/outside board."""

    student_id: str
    full_name: str
    rfid_uid: str | None
    inside: bool
