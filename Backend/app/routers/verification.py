"""
Public verification endpoint + admin audit log.

Section 6, steps 6-7 of the brief: "Verifier later checks the record by
comparing the presented data with the stored proof" -> "ATLAS shows a
simple result: verified / invalid / revoked".

In Phase 1 the comparison happens against this database. In Phase 2 the
same request shape should instead read the proof from the smart contract;
callers of this endpoint should not need to change.
"""
import datetime as _dt

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app import models, schemas
from app.database import get_db
from app.security import require_admin

router = APIRouter(tags=["verification"])


@router.get("/verify/{proof_hash}", response_model=schemas.VerificationOut)
def verify(proof_hash: str, db: Session = Depends(get_db)):
    """
    Public, unauthenticated on purpose -- anyone (employer, other
    institution) should be able to verify a credential without an account.
    Deliberately returns no private student fields (name/email/phone/etc),
    only what section 7 of the brief allows on the trust layer.
    """
    checked_at = _dt.datetime.now(_dt.timezone.utc)
    credential = db.query(models.Credential).filter(models.Credential.proof_hash == proof_hash).first()

    if not credential:
        result = models.VerificationResult.invalid
        log = models.VerificationLog(
            credential_id=None, proof_hash_checked=proof_hash, result=result
        )
        db.add(log)
        db.commit()
        return schemas.VerificationOut(result=result, proof_hash=proof_hash, checked_at=checked_at)

    result = (
        models.VerificationResult.revoked
        if credential.status == models.CredentialStatus.revoked
        else models.VerificationResult.verified
    )
    log = models.VerificationLog(
        credential_id=credential.id, proof_hash_checked=proof_hash, result=result
    )
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
