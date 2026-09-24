# ATLAS Backend — Phase 1

This is Phase 1 from the ATLAS blockchain research brief: **"Build student
records and verification API without blockchain."** No chain, no wallet, no
smart contract yet — just a private database, a hash/proof generator, and a
verification API shaped so Phase 2 can slot a blockchain in underneath it
without changing the API surface.

## What's here

| Brief requirement (section 9, MVP) | Where it lives |
|---|---|
| Student identity record | `app/models.py::Student`, `app/routers/students.py` |
| Credential issuance | `app/routers/credentials.py` |
| Hash/proof generation | `app/security.py::compute_proof_hash` |
| Smart contract verification | `app/routers/verification.py` — **stubbed locally**; Phase 2 swaps the DB lookup for a chain read |
| Verification portal | `GET /verify/{proof_hash}` (this is the API a portal would call) |
| Transaction/audit view | `app/models.py::VerificationLog`, `GET /verify-logs` |

## Design choices, and why

- **Hybrid architecture (section 6-7 of the brief):** `Student` holds every
  private field (name, email, phone, course, hostel). `Credential` never
  stores raw personal data in what would be the on-chain payload — only
  `proof_hash`, a SHA-256 digest of `{student_id, credential_type, title,
  issued_by, issued_at}`. That hash is the one thing designed to survive the
  move to a blockchain in Phase 2.
- **`/verify/{proof_hash}` is public, unauthenticated, and returns no
  private student fields** — any employer or other institution should be
  able to check a credential without an account, matching "Verifier later
  checks the record."
- **Admin endpoints (`/students`, `/credentials`, revoke, `/verify-logs`)
  require an `X-Admin-Api-Key` header.** This is intentionally simple for a
  Phase 1 prototype — the brief's risk table (section 12) flags identity
  recovery and access control as things to design properly before real
  deployment. Replace this with OAuth2/JWT + roles before then.
- **Tables are created directly from the models on startup**, not via
  migrations. Fine for a prototype; swap for Alembic before this ever holds
  real student data.

## Running it

```bash
cp .env.example .env        # then edit ADMIN_API_KEY to something real
docker compose up -d        # starts Postgres on localhost:5432
pip install -r requirements.txt
uvicorn app.main:app --reload
```

Open **http://localhost:8000/docs** for interactive Swagger docs.

## Running the tests

```bash
pytest -q
```

Tests run against an in-memory SQLite database (via a dependency override),
so no Postgres is needed just to run the suite. 8 tests cover: identity
creation, duplicate-record conflicts, proof-hash generation on issuance,
`verified` / `invalid` / `revoked` outcomes, audit logging, and that admin
auth is actually enforced.

## Example flow

```bash
KEY="your-admin-api-key"

# 1. Create a student identity
curl -s -X POST localhost:8000/students \
  -H "X-Admin-Api-Key: $KEY" -H "Content-Type: application/json" \
  -d '{"student_id":"STU001","full_name":"Asha Rao","email":"asha@example.edu","course":"B.Tech CSE"}'

# 2. Issue a credential -> get back a proof_hash
curl -s -X POST localhost:8000/credentials \
  -H "X-Admin-Api-Key: $KEY" -H "Content-Type: application/json" \
  -d '{"student_id":"STU001","credential_type":"degree","title":"B.Tech Computer Science","issued_by":"Registrar"}'

# 3. Anyone can verify it — no auth required
curl -s localhost:8000/verify/<proof_hash-from-step-2>
```

## What's deliberately NOT in this pass (per the phase plan)

- **Phase 2 — blockchain:** no smart contract, no testnet deployment yet.
  `compute_proof_hash()` is written so its output is exactly what a
  contract would later store; `verification.py` is structured so only its
  DB lookup needs to change, not its request/response shape.
- **Phase 3 — credential workflow UI**, **Phase 4 — identity integration
  with other campus services**, **Phase 5 — security/evaluation testing**,
  **Phase 6 — campus (IoT gate) integration**: all out of scope for this
  pass, per the brief's own phase ordering.

## Project layout

```
atlas-backend/
  app/
    main.py            FastAPI app, startup table creation
    config.py           Settings (env-driven)
    database.py         SQLAlchemy engine/session
    models.py            Student, Credential, VerificationLog
    schemas.py           Pydantic request/response models
    security.py           Proof-hash function + admin auth
    routers/
      students.py
      credentials.py
      verification.py
  tests/
    test_api.py          8 end-to-end tests, in-memory SQLite
  docker-compose.yml     Local Postgres
  .env.example
  requirements.txt
```
