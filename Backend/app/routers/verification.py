"""
Public verification endpoint + admin audit log.

Phase 2: /verify now reads the smart contract directly (a free, instant
view call) alongside the database lookup and returns both. The database
answers "what do we know about this credential"; the chain answers "was
this exact proof logged immutably, and has it been revoked". If the chain
is unreachable the endpoint still works and reports `on_chain: false`
with a `chain_error`, rather than failing.
"""
import datetime as _dt

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app import models, schemas
from app.chain import client as chain
from app.database import get_db
from app.security import require_admin

router = APIRouter(tags=["verification"])


@router.get("/verify/{proof_hash}", response_model=schemas.VerificationOut)
def verify(proof_hash: str, db: Session = Depends(get_db)):
    """
    Public, unauthenticated on purpose -- anyone (employer, other
    institution) should be able to verify a credential without an account.
    Deliberately returns no private student fields.
    """
    checked_at = _dt.datetime.now(_dt.timezone.utc)
    credential = db.query(models.Credential).filter(models.Credential.proof_hash == proof_hash).first()

    on_chain_info = {"exists": False, "revoked": None, "error": None}
    if len(proof_hash) == 64:
        try:
            bytes.fromhex(proof_hash)
            raw = chain.read_proof_from_chain(proof_hash)
            on_chain_info = {
                "exists": raw["exists"],
                "revoked": raw.get("revoked") if raw["exists"] else None,
                "error": raw.get("error"),
            }
        except ValueError:
            on_chain_info["error"] = "proof hash is not valid hex"

    if not credential:
        result = models.VerificationResult.invalid
        log = models.VerificationLog(credential_id=None, proof_hash_checked=proof_hash[:64], result=result)
        db.add(log)
        db.commit()
        return schemas.VerificationOut(
            result=result,
            proof_hash=proof_hash,
            checked_at=checked_at,
            on_chain=on_chain_info["exists"],
            on_chain_revoked=on_chain_info["revoked"],
            chain_error=on_chain_info["error"],
        )

    result = (
        models.VerificationResult.revoked
        if credential.status == models.CredentialStatus.revoked
        else models.VerificationResult.verified
    )
    log = models.VerificationLog(credential_id=credential.id, proof_hash_checked=proof_hash, result=result)
    db.add(log)
    db.commit()

    return schemas.VerificationOut(
        result=result,
        credential_type=credential.credential_type,
        title=credential.title,
        issued_by=credential.issued_by,
        issued_at=credential.issued_at,
        proof_hash=proof_hash,
        checked_at=checked_at,
        on_chain=on_chain_info["exists"],
        on_chain_revoked=on_chain_info["revoked"],
        chain_error=on_chain_info["error"],
    )


@router.get(
    "/verify-logs",
    response_model=list[schemas.VerificationLogOut],
    dependencies=[Depends(require_admin)],
)
def verification_logs(db: Session = Depends(get_db)):
    """Admin-only audit trail -- section 9's 'Transaction/audit view'."""
    return (
        db.query(models.VerificationLog)
        .order_by(models.VerificationLog.checked_at.desc())
        .limit(500)
        .all()
    )
