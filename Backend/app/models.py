"""
ORM models for the Phase 1 private database.

Maps directly onto section 7 of the ATLAS blockchain research brief
("What should be on-chain?"):

  KEEP IN PRIVATE DATABASE (modeled here in full)
    - Student: name, email, course, hostel, phone, vehicle, etc.
    - Credential: the operational record of what was issued to whom.

  GOING ON-CHAIN LATER (Phase 2 -- not implemented yet)
    - Credential.proof_hash only, plus credential_type + issued_at as
      minimal event metadata. See app/security.py for how the hash is
      derived, and app/routers/verification.py for the local stand-in
      for what will become a smart-contract read.
"""
import enum
import uuid
from datetime import datetime

from sqlalchemy import (
    DateTime,
    Enum,
    ForeignKey,
    String,
    func,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


def _uuid() -> str:
    return str(uuid.uuid4())


class CredentialStatus(str, enum.Enum):
    active = "active"
    revoked = "revoked"


class VerificationResult(str, enum.Enum):
    verified = "verified"
    invalid = "invalid"
    revoked = "revoked"


class Student(Base):
    """A single reusable student identity (section 1 of the brief)."""

    __tablename__ = "students"

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=_uuid)
    student_id: Mapped[str] = mapped_column(String(50), unique=True, index=True, nullable=False)
    full_name: Mapped[str] = mapped_column(String(200), nullable=False)
    email: Mapped[str] = mapped_column(String(200), unique=True, nullable=False)
    phone: Mapped[str | None] = mapped_column(String(30), nullable=True)
    course: Mapped[str | None] = mapped_column(String(200), nullable=True)
    hostel: Mapped[str | None] = mapped_column(String(100), nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    credentials: Mapped[list["Credential"]] = relationship(
        back_populates="student", cascade="all, delete-orphan"
    )


class Credential(Base):
    """
    An issued credential (certificate, micro-credential, diploma, etc).

    `proof_hash` is a SHA-256 digest of the credential's canonical,
    non-sensitive fields (see app/security.py::compute_proof_hash). It is
    the only thing designed to ever be written to a blockchain in Phase 2.
    """

    __tablename__ = "credentials"

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=_uuid)
    student_id: Mapped[str] = mapped_column(ForeignKey("students.id"), nullable=False, index=True)

    credential_type: Mapped[str] = mapped_column(String(100), nullable=False)  # e.g. "degree", "micro-credential"
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    issued_by: Mapped[str] = mapped_column(String(200), nullable=False)

    proof_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True, nullable=False)
    status: Mapped[CredentialStatus] = mapped_column(
        Enum(CredentialStatus), default=CredentialStatus.active, nullable=False
    )

    issued_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    student: Mapped["Student"] = relationship(back_populates="credentials")
    verification_logs: Mapped[list["VerificationLog"]] = relationship(
        back_populates="credential", cascade="all, delete-orphan"
    )


class VerificationLog(Base):
    """
    Audit trail of verification checks (section 9: 'Transaction/audit view').

    This is the Phase 1 stand-in for the on-chain event log Phase 2 will add.
    """

    __tablename__ = "verification_logs"

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=_uuid)
    credential_id: Mapped[str | None] = mapped_column(
        ForeignKey("credentials.id"), nullable=True, index=True
    )
    proof_hash_checked: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    result: Mapped[VerificationResult] = mapped_column(Enum(VerificationResult), nullable=False)
    verifier_note: Mapped[str | None] = mapped_column(String(300), nullable=True)
    checked_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    credential: Mapped["Credential | None"] = relationship(back_populates="verification_logs")
