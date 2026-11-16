"""
ORM models for the private database.

Maps onto section 7 of the ATLAS blockchain research brief
("What should be on-chain?"):

  KEEP IN PRIVATE DATABASE (modeled here in full)
    - Student: name, email, course, hostel, phone, rfid_uid, inside/outside.
    - Credential: the operational record of what was issued to whom.
    - GateLog: the operational record of each entry/exit attempt.

  GOING ON-CHAIN (Phase 2 -- see app/chain/client.py)
    - Only Credential.proof_hash / GateLog.proof_hash, plus a small event
      type tag and timestamp. Never raw personal data, never the RFID UID
      itself, never a name or email.
"""
import enum
import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
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


class GateDirection(str, enum.Enum):
    entry = "entry"
    exit = "exit"


class ChainEventType(int, enum.Enum):
    """Must match the AtlasRegistry.sol enum ordering exactly."""

    credential_issued = 0
    credential_revoked = 1
    gate_entry = 2
    gate_exit = 3


class ChainTxStatus(str, enum.Enum):
    pending = "pending"
    confirmed = "confirmed"
    failed = "failed"


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

    # Phase 2 (gate hardware): the RFID card UID assigned to this student,
    # as read by the MFRC522 reader (hex string, e.g. "01020304"). Nullable
    # because not every student necessarily has a card assigned yet.
    rfid_uid: Mapped[str | None] = mapped_column(String(32), unique=True, index=True, nullable=True)

    # Whether this student is currently inside campus, per the last granted
    # gate scan. Centralized here instead of living only on the ESP32, so
    # it survives a device reboot and is visible from the admin frontend.
    inside: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    credentials: Mapped[list["Credential"]] = relationship(
        back_populates="student", cascade="all, delete-orphan"
    )
    gate_logs: Mapped[list["GateLog"]] = relationship(
        back_populates="student", cascade="all, delete-orphan"
    )


class Credential(Base):
    """
    An issued credential (certificate, micro-credential, diploma, etc).

    `proof_hash` is a SHA-256 digest of the credential's canonical,
    non-sensitive fields (see app/security.py::compute_proof_hash). This is
    the thing written to the blockchain in Phase 2 (see app/chain).
    """

    __tablename__ = "credentials"

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=_uuid)
    student_id: Mapped[str] = mapped_column(ForeignKey("students.id"), nullable=False, index=True)

    credential_type: Mapped[str] = mapped_column(String(100), nullable=False)
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
    chain_txs: Mapped[list["ChainTransaction"]] = relationship(
        back_populates="credential", cascade="all, delete-orphan"
    )


class VerificationLog(Base):
    """Audit trail of proof-hash verification checks (section 9)."""

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


class GateLog(Base):
    """
    One RFID gate scan attempt (granted or denied), fed by the ESP32 over
    WiFi via POST /gate/scan. This is the Phase 2 hardware-integration
    equivalent of VerificationLog -- every attempt is recorded, not just
    successful ones, so the audit trail stays honest.
    """

    __tablename__ = "gate_logs"

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=_uuid)
    student_id: Mapped[str | None] = mapped_column(
        ForeignKey("students.id"), nullable=True, index=True
    )
    rfid_uid_scanned: Mapped[str] = mapped_column(String(32), index=True, nullable=False)
    direction: Mapped[GateDirection] = mapped_column(Enum(GateDirection), nullable=False)
    granted: Mapped[bool] = mapped_column(Boolean, nullable=False)
    reason: Mapped[str] = mapped_column(String(50), nullable=False)  # "granted", "unknown_card", "already_inside", "already_outside"

    # Only set when granted=True -- this is what gets written on-chain.
    proof_hash: Mapped[str | None] = mapped_column(String(64), index=True, nullable=True)

    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    student: Mapped["Student | None"] = relationship(back_populates="gate_logs")
    chain_txs: Mapped[list["ChainTransaction"]] = relationship(
        back_populates="gate_log", cascade="all, delete-orphan"
    )


class ChainTransaction(Base):
    """
    Tracks each blockchain write the backend has made or attempted, for
    either a Credential event or a GateLog event. Written by a background
    task (see app/chain/client.py) so the HTTP response to the caller --
    the gate device, or the admin frontend -- never waits on chain
    confirmation (per the "open gate immediately, log async" design).
    """

    __tablename__ = "chain_transactions"

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=_uuid)

    credential_id: Mapped[str | None] = mapped_column(
        ForeignKey("credentials.id"), nullable=True, index=True
    )
    gate_log_id: Mapped[str | None] = mapped_column(
        ForeignKey("gate_logs.id"), nullable=True, index=True
    )

    proof_hash: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    event_type: Mapped[int] = mapped_column(nullable=False)  # ChainEventType value

    tx_hash: Mapped[str | None] = mapped_column(String(80), nullable=True)
    status: Mapped[ChainTxStatus] = mapped_column(
        Enum(ChainTxStatus), default=ChainTxStatus.pending, nullable=False
    )
    error: Mapped[str | None] = mapped_column(String(500), nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    credential: Mapped["Credential | None"] = relationship(back_populates="chain_txs")
    gate_log: Mapped["GateLog | None"] = relationship(back_populates="chain_txs")
