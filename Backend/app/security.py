"""
Proof-hash generation and shared-secret authentication.

compute_proof_hash() defines exactly what gets committed on-chain in
Phase 2. Keep it minimal and stable -- section 7 of the brief is explicit
that only "minimal data required to prove integrity" belongs here, never
raw personal data.
"""
import hashlib
import json

from fastapi import Depends, HTTPException, status
from fastapi.security import APIKeyHeader

from app.config import get_settings

settings = get_settings()

_admin_key_header = APIKeyHeader(name="X-Admin-Api-Key", auto_error=False)
_device_key_header = APIKeyHeader(name="X-Device-Api-Key", auto_error=False)


def compute_proof_hash(
    *,
    student_id: str,
    credential_type: str,
    title: str,
    issued_by: str,
    issued_at_iso: str,
) -> str:
    """
    Deterministic SHA-256 hash over the canonical, non-sensitive fields of
    a credential. This -- and only this -- is what Phase 2 writes to the
    blockchain (as the smart-contract "proof" for the record).

    Field order is fixed via an explicit dict + sort_keys=True so the same
    credential always hashes the same way, on any machine.
    """
    canonical = {
        "student_id": student_id,
        "credential_type": credential_type,
        "title": title,
        "issued_by": issued_by,
        "issued_at": issued_at_iso,
    }
    payload = json.dumps(canonical, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def compute_gate_proof_hash(
    *,
    student_id: str,
    direction: str,
    occurred_at_iso: str,
) -> str:
    """
    Same idea as compute_proof_hash, but for a gate entry/exit event. Never
    includes the RFID UID itself -- only the human-readable student_id,
    which is already treated as semi-public (it's printed on the ID card),
    the direction, and the timestamp.
    """
    canonical = {
        "student_id": student_id,
        "direction": direction,
        "occurred_at": occurred_at_iso,
    }
    payload = json.dumps(canonical, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def require_admin(api_key: str | None = Depends(_admin_key_header)) -> None:
    """
    Guards issuer/admin-only endpoints (create student, issue credential,
    revoke, view audit log, gate logs) with a shared-secret header.

    This is deliberately simple for a prototype. Section 5 of the brief's
    risk table calls out identity/key recovery and access control as
    things to define properly before any real deployment -- replace this
    with OAuth2/JWT + roles at that point.
    """
    if not api_key or api_key != settings.admin_api_key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing or invalid admin API key",
        )


def require_device(api_key: str | None = Depends(_device_key_header)) -> None:
    """
    Guards the gate-scan endpoint. Separate from the admin key on purpose:
    the ESP32 only needs permission to submit scans, never to manage
    students, credentials, or read the audit log.
    """
    if not api_key or api_key != settings.device_api_key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing or invalid device API key",
        )
