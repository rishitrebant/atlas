# ATLAS Phase 2 — setup guide

Everything here is individual files that mirror your repo layout. Copy each one to the same path in your repo (overwrite when asked), commit, push.

## 1. Where each file goes

| File in this delivery | Put it at (repo root = your `Atlas/` folder) | New or replaced |
|---|---|---|
| `Backend/app/config.py` | `Backend/app/config.py` | replaced |
| `Backend/app/models.py` | `Backend/app/models.py` | replaced |
| `Backend/app/schemas.py` | `Backend/app/schemas.py` | replaced |
| `Backend/app/security.py` | `Backend/app/security.py` | replaced |
| `Backend/app/main.py` | `Backend/app/main.py` | replaced |
| `Backend/app/chain/__init__.py` | `Backend/app/chain/__init__.py` | **new** |
| `Backend/app/chain/client.py` | `Backend/app/chain/client.py` | **new** |
| `Backend/app/chain/AtlasRegistry.abi.json` | `Backend/app/chain/AtlasRegistry.abi.json` | **new** |
| `Backend/app/routers/students.py` | `Backend/app/routers/students.py` | replaced |
| `Backend/app/routers/credentials.py` | `Backend/app/routers/credentials.py` | replaced |
| `Backend/app/routers/verification.py` | `Backend/app/routers/verification.py` | replaced |
| `Backend/app/routers/gate.py` | `Backend/app/routers/gate.py` | **new** |
| `Backend/scripts/seed_students.py` | `Backend/scripts/seed_students.py` | **new** (also add an empty `Backend/scripts/__init__.py`) |
| `Backend/requirements.txt` | `Backend/requirements.txt` | replaced (adds `web3`) |
| `Backend/.env.example` | `Backend/.env.example` | **new** (copy to `.env`, never commit `.env`) |
| `blockchain/` (whole folder) | `blockchain/` | **new** |
| `Hardware/wokwi/src/main.cpp` | `Hardware/wokwi/src/main.cpp` | replaced |
| `Hardware/wokwi/src/config.h` | `Hardware/wokwi/src/config.h` | **new** |
| `Hardware/wokwi/platformio.ini` | `Hardware/wokwi/platformio.ini` | replaced (adds ArduinoJson) |
| `Hardware/wokwi/diagram.json` | `Hardware/wokwi/diagram.json` | replaced (ESP32-CAM removed) |
| `Frontend/index.html`, `app.js`, `app.css` | `Frontend/` (same names) | replaced |

`database.py` and `docker-compose.yml` are unchanged.
Make sure `Backend/app/chain/`, `Backend/app/routers/` and `Backend/scripts/` each contain an `__init__.py`.

## 2. One-time setup

```bash
# Backend deps (inside your existing venv)
cd Backend
pip install -r requirements.txt
cp .env.example .env          # then edit the two keys below

# Blockchain deps
cd ../blockchain
npm install
```

Edit `Backend/.env`:
- `ADMIN_API_KEY` — pick any secret string (used by the web UI).
- `DEVICE_API_KEY` — pick a different secret (used by the ESP32). Must equal `DEVICE_API_KEY` in `config.h`.
- `CONTRACT_ADDRESS` — filled in at step 3.
- Leave `WEB3_PRIVATE_KEY` as is. It is Hardhat's public test key and is worthless; it only works on the local chain.

## 3. Run it (3 terminals, in this order)

**Terminal 1 — local blockchain** (leave running; it forgets everything when stopped)
```bash
cd blockchain
npm run node
```

**Terminal 2 — deploy the contract, then start the backend**
```bash
cd blockchain
npm run deploy
# prints:  CONTRACT_ADDRESS=0x....   -> paste that line into Backend/.env

cd ../Backend
docker compose up -d
python -m scripts.seed_students        # creates the 3 test students (once)
uvicorn app.main:app --reload --host 0.0.0.0
```
`--host 0.0.0.0` is required so the ESP32 can reach the laptop.

**Browser:** http://localhost:8000/ → click “Admin key”, enter your `ADMIN_API_KEY`, press Apply. Open **Campus gate**.

> Restarting Terminal 1 wipes the chain. Then re-run `npm run deploy`, update `CONTRACT_ADDRESS`, and restart uvicorn. Old DB rows will show “chain failed/not found” — that is expected on a dev chain.

## 4. Flash the ESP32

1. Find the laptop's LAN IP: Windows `ipconfig` → IPv4; Mac `ipconfig getifaddr en0`; Linux `hostname -I`.
2. Edit `Hardware/wokwi/src/config.h`: `WIFI_SSID`, `WIFI_PASSWORD` (2.4 GHz only), `BACKEND_HOST` (that IP), `DEVICE_API_KEY`.
3. Laptop and ESP32 must be on the same WiFi. Allow inbound port 8000 in the laptop firewall (Windows will prompt the first time).
4. Upload with PlatformIO, open the serial monitor (115200). You should see `WiFi OK, IP: ...`, and the LCD shows the IP.
5. Tap a card. The LCD says VERIFYING…, the gate opens, and the row appears on the Campus gate page with a `⛓ on-chain` badge a second later.

Test the network path before touching hardware: Campus gate page → “Simulate a scan”, or open `http://<laptop-ip>:8000/health` from your phone on the same WiFi.

Don't push your real WiFi password: after editing, run
`git update-index --skip-worktree Hardware/wokwi/src/config.h`

## 5. How it behaves

- **Open first, log later:** the gate opens right after the database check; the blockchain write happens in the background and never delays the gate.
- **Fail closed:** if WiFi, the server, or the device key is wrong, the gate stays shut and the LCD says why (`NO WIFI`, `SERVER OFFLINE`, `BAD DEVICE KEY`).
- **Entry/exit rules:** server-side. Entering twice → “Already inside”; exiting without entering → “Already outside”; unknown card → denied. All attempts are in the gate log; only granted ones go on-chain.
- **On-chain data:** only SHA-256 proof hashes plus an event type and timestamp. Never names, emails or card UIDs.
- **Adding a real student with a card:** tap the card, read `Card UID:` in the serial monitor, then create the student in the UI with that UID (or `PATCH /students/{id}/rfid`).

## 6. Hardware notes (real circuit)

- HC-SR04 ECHO outputs 5 V: put a 1 kΩ + 2 kΩ divider between ECHO and GPIO34.
- Servos: power from an external 5 V supply, with its ground tied to the ESP32 ground. Don't run both from the ESP32's 3V3 pin.
- The ESP32-CAM was removed from `diagram.json`; the final circuit has no camera or ML.
- The ultrasonic sensor only drives the idle “APPROACH: SCAN” message; it doesn't control the gate.

## 7. What was tested here

Backend + contract end to end (entry, exit, repeat-entry, exit-without-entry, unknown card, colon-formatted UIDs, credential issue/revoke/verify, forged hash, wrong/missing keys) against a live local chain: all pass. The web UI was exercised in a real browser against that stack. The firmware was syntax-checked only — it has not been compiled or run on a physical ESP32 (no toolchain in the build environment), so expect to fix at most small compile issues on first build.
