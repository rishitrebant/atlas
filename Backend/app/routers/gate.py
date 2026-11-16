"""
Gate endpoints -- the bridge between the ESP32 hardware and the backend.

POST /gate/scan is called by the ESP32 each time a card is tapped at the
entry or exit reader. The flow, per the "open immediately, log async"
design:

  1. Look the card UID up in the database.        (fast, <100ms)
  2. Decide granted / denied, update inside/outside state.
  3. Write a GateLog row.
  4. Return the decision to the ESP32 so it can drive the servo/LEDs/LCD.
  5. AFTER the response is sent, write the proof hash to the blockchain in
     a background task. The gate never waits on chain confirmation.

Only *granted* scans get a proof hash and an on-chain record. Denied scans
are still logged in the database for the audit trail, but are not written
to the chain (nothing happened that needs tamper-evident proof).
"""
import datetime as _dt

from fastapi import APIRouter, BackgroundTasks, Depends
from sqlalchemy.orm import Session

from app import models, schemas
from app.chain import client as chain
from app.database import get_db
from app.security import compute_gate_proof_hash, require_admin, require_device

router = APIRouter(prefix="/gate", tags=["gate"])


def _normalize_uid(uid: str) -> str:
    return uid.replace(":", "").replace(" ", "").strip().upper()


@router.post("/scan", response_model=schemas.GateScanOut, dependencies=[Depends(require_device)])
def scan(
    payload: schemas.GateScanRequest,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
):
    uid = _normalize_uid(payload.uid)
    direction = payload.direction

    student = db.query(models.Student).filter(models.Student.rfid_uid == uid).first()

    def deny(reason: str, message: str, student_obj: models.Student | None = None) -> schemas.GateScanOut:
        db.add(
            models.GateLog(
                student_id=student_obj.id if student_obj else None,
                rfid_uid_scanned=uid,
                direction=direction,
                granted=False,
                reason=reason,
            )
        )
        db.commit()
        return schemas.GateScanOut(
            granted=False,
            reason=reason,
            message=message,
            student_name=student_obj.full_name if student_obj else None,
            student_id=student_obj.student_id if student_obj else None,
        )

    if not student:
        return deny("unknown_card", "Unknown card")

    if direction == models.GateDirection.entry and student.inside:
        return deny("already_inside", "Already inside", student)

    if direction == models.GateDirection.exit and not student.inside:
        return deny("already_outside", "Already outside", student)

    occurred_at = _dt.datetime.now(_dt.timezone.utc)
    proof_hash = compute_gate_proof_hash(
        student_id=student.student_id,
        direction=direction.value,
        occurred_at_iso=occurred_at.isoformat(),
    )

    student.inside = direction == models.GateDirection.entry
    gate_log = models.GateLog(
        student_id=student.id,
        rfid_uid_scanned=uid,
        direction=direction,
        granted=True,
        reason="granted",
        proof_hash=proof_hash,
        occurred_at=occurred_at,
    )
    db.add(gate_log)
    db.commit()
    db.refresh(gate_log)

    event_type = (
        models.ChainEventType.gate_entry
        if direction == models.GateDirection.entry
        else models.ChainEventType.gate_exit
    )
    background_tasks.add_task(
        chain.log_event_in_background,
        proof_hash,
        event_type.value,
        gate_log_id=gate_log.id,
    )

    verb = "Entry" if direction == models.GateDirection.entry else "Exit"
    return schemas.GateScanOut(
        granted=True,
        reason="granted",
        message=f"{verb} granted",
        student_name=student.full_name,
        student_id=student.student_id,
        proof_hash=proof_hash,
    )


@router.get("/logs", response_model=list[schemas.GateLogOut], dependencies=[Depends(require_admin)])
def gate_logs(db: Session = Depends(get_db)):
    logs = (
        db.query(models.GateLog)
        .order_by(models.GateLog.occurred_at.desc())
        .limit(200)
        .all()
    )
    out = []
    for log in logs:
        chain_status = None
        if log.chain_txs:
            latest = max(log.chain_txs, key=lambda t: t.created_at)
            chain_status = schemas.ChainStatusOut(
                tx_hash=latest.tx_hash, status=latest.status, error=latest.error
            )
        out.append(
            schemas.GateLogOut(
                id=log.id,
                student_id=log.student.student_id if log.student else None,
                rfid_uid_scanned=log.rfid_uid_scanned,
                direction=log.direction,
                granted=log.granted,
                reason=log.reason,
                proof_hash=log.proof_hash,
                occurred_at=log.occurred_at,
                chain=chain_status,
            )
        )
    return out


@router.get("/status", response_model=list[schemas.GateStatusOut], dependencies=[Depends(require_admin)])
def gate_status(db: Session = Depends(get_db)):
    """Live inside/outside board for the frontend."""
    students = db.query(models.Student).order_by(models.Student.full_name).all()
    return [
        schemas.GateStatusOut(
            student_id=s.student_id,
            full_name=s.full_name,
            rfid_uid=s.rfid_uid,
            inside=s.inside,
        )
        for s in students
    ]
