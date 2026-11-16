# ATLAS — Build Roadmap

A phased plan for building ATLAS as a real, blockchain-based system, with ML facial recognition and IoT RFID gate entry layered in once the core is solid.

## Guiding principle

**Don't build blockchain + ML + IoT simultaneously.** Each is a full subsystem with its own failure modes. Build them as separate, independently-testable modules, and only wire them together once each one works on its own. This also splits naturally across a 2–3 person team.

---

## Team & repo setup

- **One shared GitHub repository.** Whoever sets it up adds the other 2 as direct collaborators (write access) — don't use a fork-based workflow, that's for open-source projects with untrusted contributors.
- **Protect `main`:** no direct pushes; require a pull request + at least 1 review before merge.
- **Branch naming:** `feature/<short-desc>` (e.g. `feature/rfid-reader`, `feature/face-match-api`, `feature/smart-contract-verify`).
- Optional: a `dev` branch as an integration buffer, merged to `main` at milestones.
- **Suggested role split (2–3 people):**
  - Person A: Backend + smart contract / blockchain integration
  - Person B: ML face recognition service + web/app frontend
  - Person C (if 3): IoT hardware (RFID + camera) + systems integration/testing
  - If only 2 people, combine B and C.

---

## Phase 0 — Scope & design (1 week)

- Finalize which slide-3 use cases are in scope for a working demo (recommend: **Gate Entry only** for v1 — it's the one with hardware, ML, and blockchain all touching it; the rest — library, events, parking — can stay as "roadmap" slides).
- Write a one-page technical spec: what data lives where (private DB vs. blockchain), what each service's API looks like, what hardware you're actually sourcing.
- Set up the repo, branch protection, and a shared task board (GitHub Projects/Trello/Notion).

## Phase 1 — Core backend + student records (no blockchain, no ML, no hardware)

**Goal:** a working system with fake/manual data so everyone can build against a real API.

- Backend API (Node/Express or Python/FastAPI — pick based on team's strongest language, FastAPI pairs well with the ML service later).
- Database (Postgres or MongoDB) for student records: `student_id`, `name`, `RFID_tag_id`, `face_embedding_reference`, enrollment status.
- Basic admin panel: add/view students, manually trigger a "gate entry" for testing.
- Basic student-facing web page: view your own ID/status.
- **No blockchain yet.** Just log entries to the normal DB with a timestamp.

*Deliverable: you can add a student, and simulate an entry via a button click that writes a row to the DB.*

## Phase 2 — Blockchain integration

**Goal:** replace the "log to DB" step with a real on-chain verification record, without touching ML/IoT yet.

- Decide on chain type:
  - **Public testnet (Polygon, or similar EVM-compatible testnet)** — easiest to demo, free test tokens, good tooling (Hardhat/Remix), but public devs should know testnets get deprecated/renamed periodically — check current recommended EVM testnet at build time.
  - **Permissioned chain (Hyperledger Fabric)** — more "enterprise campus" realistic, but heavier setup, steeper learning curve for a student team.
  - **Recommendation for a first build:** public EVM testnet + Solidity smart contract. Faster to get working, plenty of tutorials, easy to demo with a block explorer link.
- Write a smart contract with one core function: `logVerification(studentIdHash, eventType, timestamp)` → emits an event, returns a tx hash.
- **Only a hash of the identity + event goes on-chain.** Actual student data stays in the private DB (this matches what's already in your deck's slide 4 — keep that architecture).
- Backend calls the smart contract via ethers.js/web3.py when an entry event happens.
- Update the admin panel to show the resulting transaction hash / block explorer link, so you can prove it's really on-chain.

*Deliverable: clicking "simulate gate entry" now produces a real blockchain transaction you can verify on a testnet explorer.*

## Phase 3 — ML facial recognition (built and tested standalone)

**Goal:** a face-matching microservice you can test with a web form before any hardware exists.

- Separate Python microservice (FastAPI + `face_recognition` (dlib-based, simpler) or `DeepFace`/InsightFace (more accurate, slightly heavier)).
- Enrollment: capture a reference photo per student at signup → generate + store a face embedding (not the raw photo, for privacy) linked to their student ID.
- Verification endpoint: accepts a new photo → generates its embedding → compares to the stored one → returns match/no-match + confidence score.
- Test via a simple web upload form first — don't wait for hardware.
- Decide your confidence threshold deliberately (test with siblings/lookalikes/lighting variation) and log false-accept/false-reject rates — this is the number you'll get asked about in review.

*Deliverable: upload a photo, get back "match: student X, confidence 0.94" or "no match."*

## Phase 4 — Wire ML + blockchain together

**Goal:** one backend endpoint that does the full verified-entry logic, still triggered manually (button, not hardware).

- New endpoint: `POST /verify-entry` — takes `{tag_id, photo}` → looks up student by tag → calls ML service to compare photo to stored embedding → if match: calls smart contract to log entry, returns "access granted" → if no match: logs a flagged attempt, returns "access denied."
- This is the full logical flow from the diagram above, just without real RFID/camera hardware yet — you trigger it from a test form.

*Deliverable: a single API call simulates the entire gate-entry decision, end-to-end, including the real blockchain write.*

## Phase 5 — IoT hardware (RFID + camera)

**Goal:** replace the manual trigger with real hardware at a mock gate.

- **Hardware:** ESP32 (has WiFi built in) + MFRC522 RFID reader module + a camera (ESP32-CAM module, or a separate Raspberry Pi + Pi Camera if the ESP32-CAM's resolution/processing is too limited for reliable face capture — test both if you have components).
- **Flow on the device:**
  1. RFID reader detects a tag → reads tag ID.
  2. Triggers the camera to capture a photo.
  3. Device sends `{tag_id, photo}` to your Phase 4 backend endpoint over WiFi (HTTP POST).
  4. Backend responds with access granted/denied.
  5. Device triggers a relay/servo to physically unlock the gate (or just an LED + buzzer for a demo — don't over-engineer the physical lock for a first prototype).
- Handle the realistic failure cases: no WiFi, backend timeout, poor lighting for the camera — default to "deny + log" on any uncertainty, never fail open.

*Deliverable: physically tap a card, get your face scanned, gate/LED responds, and a real blockchain transaction is created — this is your demo.*

## Phase 6 — Integration testing, polish, docs

- Test the full flow repeatedly with multiple people, multiple lighting conditions, multiple tag reads.
- Write a short technical README + architecture diagram for the repo (mirrors your deck's slide 4/7).
- Prepare a live demo script — this matters as much as the code for how the project lands.
- If time allows: add one more use case from slide 3 (e.g. Library) reusing the same identity + blockchain layer, to demonstrate the "one identity, many services" pitch isn't just gate entry.

---

## Using AI tools through this

- **Claude Code / Cursor** — scaffold backend routes, write the Solidity contract boilerplate, generate test data, debug ESP32 C++ firmware.
- **Smart contract specific:** use Remix IDE for quick contract iteration before wiring it into your backend; Hardhat once you need scripted deployment + tests.
- Keep AI-generated code reviewed in PRs like anything else — especially the smart contract (bugs there are harder to patch after deployment) and anything handling face data (privacy-sensitive).

## Key things to decide before Phase 2

1. Public testnet vs. permissioned chain (recommend public testnet for speed).
2. What exactly goes on-chain vs. stays in the private DB (recommend: only hashes/proofs on-chain, matching your existing deck).
3. Face data storage: store embeddings, not raw photos, and be ready to explain your privacy/compliance stance (FERPA-equivalent) if asked.
