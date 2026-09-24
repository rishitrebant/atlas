"""
Credential issuance endpoints (admin/issuer only).

Covers three of the six MVP items from section 9 of the brief:
"Credential issuance", "Hash/proof generation", and (via revoke) the
status half of "Smart contract verification" -- Phase 1 keeps that
check local; Phase 2 moves the source of truth on-chain without
changing this API's shape.
"""
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app import models, schemas
from app.database import get_db
from app.security import compute_proof_hash, require_admin

router = APIRouter(prefix="/credentials", tags=["credentials"], dependencies=[Depends(require_admin)])


@router.post("", response_model=schemas.CredentialOut, status_code=status.HTTP_201_CREATED)
def issue_credential(payload: schemas.CredentialCreate, db: Session = Depends(get_db)):
    student = (
        db.query(models.Student)
        .filter(models.Student.student_id == payload.student_id)
        .first()
    )
    if not student:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Student not found")

    # issued_at is set at commit time by the DB; we need a value to hash
    # against *before* insert, so we derive it up front and store it via
    # the ORM default rather than letting the server_default diverge.
    import datetime as _dt

    issued_at = _dt.datetime.now(_dt.timezone.utc)

    proof_hash = compute_proof_hash(
        student_id=student.student_id,
        credential_type=payload.credential_type,
        title=payload.title,
        issued_by=payload.issued_by,
        issued_at_iso=issued_at.isoformat(),
    )

    credential = models.Credential(
        student_id=student.id,
        credential_type=payload.credential_type,
        title=payload.title,
        issued_by=payload.issued_by,
        proof_hash=proof_hash,
        issued_at=issued_at,
    )
    db.add(credential)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A credential with this exact proof already exists (duplicate issuance)",
        )
    db.refresh(credential)
    return _to_out(credential, student.student_id)


@router.get("/{credential_id}", response_model=schemas.CredentialOut)
def get_credential(credential_id: str, db: Session = Depends(get_db)):
    credential = db.query(models.Credential).filter(models.Credential.id == credential_id).first()
    if not credential:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Credential not found")
    return _to_out(credential, credential.student.student_id)


@router.post("/{credential_id}/revoke", response_model=schemas.CredentialOut)
def revoke_credential(credential_id: str, db: Session = Depends(get_db)):
    import datetime as _dt

    credential = db.query(models.Credential).filter(models.Credential.id == credential_id).first()
    if not credential:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Credential not found")

    credential.status = models.CredentialStatus.revoked
    credential.revoked_at = _dt.datetime.now(_dt.timezone.utc)
    db.commit()
    db.refresh(credential)
    return _to_out(credential, credential.student.student_id)


@router.get("", response_model=list[schemas.CredentialOut])
def list_credentials(student_id: str | None = None, db: Session = Depends(get_db)):
    query = db.query(models.Credential)
    if student_id:
        query = query.join(models.Student).filter(models.Student.student_id == student_id)
    return [_to_out(c, c.student.student_id) for c in query.order_by(models.Credential.issued_at.desc())]


def _to_out(credential: models.Credential, human_student_id: str) -> schemas.CredentialOut:
    return schemas.CredentialOut(
        id=credential.id,
        student_id=human_student_id,
        credential_type=credential.credential_type,
        title=credential.title,
        issued_by=credential.issued_by,
        proof_hash=credential.proof_hash,
        status=credential.status,
        issued_at=credential.issued_at,
        revoked_at=credential.revoked_at,
    )
