"""
End-to-end tests against an in-memory SQLite DB (swapped in via dependency
override, so `pytest` needs no running Postgres). Covers the Phase 1 MVP
checklist from section 9 of the brief: identity record, credential
issuance, hash generation, and verified/invalid/revoked verification.
"""
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base, get_db
from app.main import app
from app.security import require_admin

# --- isolated in-memory DB for tests ---
engine = create_engine(
    "sqlite://",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def _override_get_db():
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()


app.dependency_overrides[get_db] = _override_get_db
app.dependency_overrides[require_admin] = lambda: None  # auth covered separately below


@pytest.fixture(autouse=True)
def _fresh_db():
    Base.metadata.create_all(bind=engine)
    yield
    Base.metadata.drop_all(bind=engine)


client = TestClient(app)


def _make_student():
    resp = client.post(
        "/students",
        json={
            "student_id": "STU001",
            "full_name": "Asha Rao",
            "email": "asha@example.edu",
            "course": "B.Tech CSE",
            "hostel": "Block C",
        },
    )
    assert resp.status_code == 201
    return resp.json()


def test_create_and_fetch_student():
    student = _make_student()
    resp = client.get(f"/students/{student['student_id']}")
    assert resp.status_code == 200
    assert resp.json()["full_name"] == "Asha Rao"


def test_duplicate_student_conflicts():
    _make_student()
    resp = client.post(
        "/students",
        json={
            "student_id": "STU001",
            "full_name": "Someone Else",
            "email": "other@example.edu",
        },
    )
    assert resp.status_code == 409


def test_issue_credential_generates_proof_hash():
    _make_student()
    resp = client.post(
        "/credentials",
        json={
            "student_id": "STU001",
            "credential_type": "micro-credential",
            "title": "Intro to Blockchain",
            "issued_by": "Dept. of CSE",
        },
    )
    assert resp.status_code == 201
    body = resp.json()
    assert len(body["proof_hash"]) == 64  # sha256 hex digest
    assert body["status"] == "active"


def test_verify_active_credential_is_verified():
    _make_student()
    cred = client.post(
        "/credentials",
        json={
            "student_id": "STU001",
            "credential_type": "degree",
            "title": "B.Tech Computer Science",
            "issued_by": "Registrar",
        },
    ).json()

    resp = client.get(f"/verify/{cred['proof_hash']}")
    assert resp.status_code == 200
    body = resp.json()
    assert body["result"] == "verified"
    assert body["title"] == "B.Tech Computer Science"
    # public verification must never leak private student fields
    assert "email" not in body
    assert "full_name" not in body


def test_verify_unknown_hash_is_invalid():
    resp = client.get("/verify/" + "0" * 64)
    assert resp.status_code == 200
    assert resp.json()["result"] == "invalid"


def test_revoked_credential_is_reported_revoked():
    _make_student()
    cred = client.post(
        "/credentials",
        json={
            "student_id": "STU001",
            "credential_type": "certificate",
            "title": "Hackathon Winner",
            "issued_by": "Student Affairs",
        },
    ).json()

    revoke_resp = client.post(f"/credentials/{cred['id']}/revoke")
    assert revoke_resp.status_code == 200
    assert revoke_resp.json()["status"] == "revoked"

    verify_resp = client.get(f"/verify/{cred['proof_hash']}")
    assert verify_resp.json()["result"] == "revoked"


def test_audit_log_records_every_verification_check():
    _make_student()
    cred = client.post(
        "/credentials",
        json={
            "student_id": "STU001",
            "credential_type": "certificate",
            "title": "Dean's List",
            "issued_by": "Registrar",
        },
    ).json()
    client.get(f"/verify/{cred['proof_hash']}")
    client.get("/verify/" + "f" * 64)

    logs = client.get("/verify-logs").json()
    assert len(logs) == 2
    results = {log["result"] for log in logs}
    assert results == {"verified", "invalid"}


def test_admin_endpoints_require_api_key_when_enforced():
    # Re-check auth wiring in isolation, without the blanket override above.
    app.dependency_overrides.pop(require_admin, None)
    try:
        resp = client.post(
            "/students",
            json={"student_id": "STU002", "full_name": "X", "email": "x@example.edu"},
        )
        assert resp.status_code == 401
    finally:
        app.dependency_overrides[require_admin] = lambda: None
