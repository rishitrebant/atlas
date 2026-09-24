"""
Proof-hash generation and admin authentication.

compute_proof_hash() is the single most important function in this
codebase for the project's research goals: it defines exactly what would
be committed on-chain in Phase 2. Keep it minimal and stable -- section 7
of the brief is explicit that only "minimal data required to prove
integrity" belongs here, never raw personal data.
"""
import hashlib
import json

from fastapi import Depends, HTTPException, status
from fastapi.security import APIKeyHeader

from app.config import get_settings

settings = get_settings()

_admin_key_header = APIKeyHeader(name="X-Admin-Api-Key", auto_error=False)


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
    a credential. This -- and only this -- is what Phase 2 will write to
    the blockchain (as the smart-contract "proof" for the record).

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


def require_admin(api_key: str | None = Depends(_admin_key_header)) -> None:
    """
    Guards issuer/admin-only endpoints (create student, issue credential,
    revoke, view audit log) with a shared-secret header.

    This is deliberately simple for a Phase 1 prototype. Section 5 of the
    brief's risk table calls out identity/key recovery and access control
    as things to define properly before any real deployment -- replace
    this with OAuth2/JWT + roles at that point.
    """
    if not api_key or api_key != settings.admin_api_key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing or invalid admin API key",
        )
