"""
Credential issuance endpoints (admin/issuer only).

Phase 2: after the database commit, the proof hash is written to the
AtlasRegistry smart contract in a background task, so the API response is
never delayed by chain confirmation. The response's `chain` field shows
the current state of that write (usually "pending" right after issuance;
call GET /credentials/{id} again a second later to see "confirmed").
"""
import datetime as _dt

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app import models, schemas
from app.chain import client as chain
from app.database import get_db
from app.security import compute_proof_hash, require_admin

router = APIRouter(prefix="/credentials", tags=["credentials"], dependencies=[Depends(require_admin)])


@router.post("", response_model=schemas.CredentialOut, status_code=status.HTTP_201_CREATED)
def issue_credential(
    payload: schemas.CredentialCreate,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
):
    student = (
        db.query(models.Student)
        .filter(models.Student.student_id == payload.student_id)
        .first()
    )
    if not student:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Student not found")

    # issued_at must be known *before* insert because it is part of the hash.
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

    background_tasks.add_task(
        chain.log_event_in_background,
        proof_hash,
        models.ChainEventType.credential_issued.value,
        credential_id=credential.id,
    )

    return _to_out(credential, student.student_id)


@router.get("/{credential_id}", response_model=schemas.CredentialOut)
def get_credential(credential_id: str, db: Session = Depends(get_db)):
    credential = db.query(models.Credential).filter(models.Credential.id == credential_id).first()
    if not credential:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Credential not found")
    return _to_out(credential, credential.student.student_id)


@router.post("/{credential_id}/revoke", response_model=schemas.CredentialOut)
def revoke_credential(
    credential_id: str,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
):
    credential = db.query(models.Credential).filter(models.Credential.id == credential_id).first()
    if not credential:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Credential not found")

    if credential.status == models.CredentialStatus.revoked:
        return _to_out(credential, credential.student.student_id)

    credential.status = models.CredentialStatus.revoked
    credential.revoked_at = _dt.datetime.now(_dt.timezone.utc)
    db.commit()
    db.refresh(credential)

    background_tasks.add_task(
        chain.log_revoke_in_background,
        credential.proof_hash,
        credential_id=credential.id,
    )

    return _to_out(credential, credential.student.student_id)


@router.get("", response_model=list[schemas.CredentialOut])
def list_credentials(student_id: str | None = None, db: Session = Depends(get_db)):
    query = db.query(models.Credential)
    if student_id:
        query = query.join(models.Student).filter(models.Student.student_id == student_id)
    return [_to_out(c, c.student.student_id) for c in query.order_by(models.Credential.issued_at.desc())]


def _latest_chain_status(credential: models.Credential) -> schemas.ChainStatusOut | None:
    """Most recent chain transaction for this credential (issue or revoke)."""
    if not credential.chain_txs:
        return None
    latest = max(credential.chain_txs, key=lambda t: t.created_at)
    return schemas.ChainStatusOut(tx_hash=latest.tx_hash, status=latest.status, error=latest.error)


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
        chain=_latest_chain_status(credential),
    )
