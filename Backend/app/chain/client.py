"""
Phase 2: thin wrapper around web3.py for talking to AtlasRegistry.sol on
the local Hardhat devnet.

Design notes (see also the top-level build README):

- Only ever writes a bytes32 proof hash + a small event-type int. Never
  raw student data. The private database (Postgres) stays the source of
  truth for everything else.
- Writes happen from a FastAPI BackgroundTask (see log_event_in_background
  / log_revoke_in_background below), never on the request path. This is
  what makes "open the gate immediately, log to chain in the background"
  possible: the gate-scan response comes back as soon as the database
  check is done, and the chain write happens after that response is
  already on the wire.
- A single process-local lock serializes chain writes. This is a student
  prototype talking to a local devnet from one backend process -- it
  doesn't need a production nonce-management strategy, but two scans
  arriving within the same instant could otherwise both read the same
  "next nonce" and collide. The lock makes that impossible within this
  process.
"""
import json
import threading
from datetime import datetime, timezone
from pathlib import Path

from web3 import Web3

from app.config import get_settings

settings = get_settings()

_ABI_PATH = Path(__file__).parent / "AtlasRegistry.abi.json"
_abi = json.loads(_ABI_PATH.read_text())

_tx_lock = threading.Lock()


class ChainNotConfigured(Exception):
    pass


def _get_w3() -> Web3:
    return Web3(Web3.HTTPProvider(settings.web3_rpc_url))


def _get_contract(w3: Web3):
    if not settings.contract_address:
        raise ChainNotConfigured(
            "CONTRACT_ADDRESS is not set. Run `node deploy.js` in blockchain/ "
            "and paste the printed address into Backend/.env."
        )
    return w3.eth.contract(address=Web3.to_checksum_address(settings.contract_address), abi=_abi)


def _hex0x(b) -> str:
    h = b.hex()
    return h if h.startswith("0x") else "0x" + h


def _to_bytes32(proof_hash_hex: str) -> bytes:
    """A SHA-256 hex digest is exactly 32 bytes -- this just decodes it,
    it does not re-hash anything."""
    return bytes.fromhex(proof_hash_hex)


def _send_log_proof(proof_hash_hex: str, event_type: int) -> str:
    if not settings.chain_enabled:
        raise ChainNotConfigured("Chain writes are disabled (CHAIN_ENABLED=false).")

    w3 = _get_w3()
    if not w3.is_connected():
        raise ConnectionError(
            f"Could not reach the local chain at {settings.web3_rpc_url}. "
            "Is `npx hardhat node` running in blockchain/?"
        )

    contract = _get_contract(w3)
    account = w3.eth.account.from_key(settings.web3_private_key)
    proof_bytes = _to_bytes32(proof_hash_hex)

    with _tx_lock:
        nonce = w3.eth.get_transaction_count(account.address, "pending")
        tx = contract.functions.logProof(proof_bytes, event_type).build_transaction(
            {
                "from": account.address,
                "nonce": nonce,
                "gas": 200_000,
                "gasPrice": w3.eth.gas_price,
            }
        )
        signed = account.sign_transaction(tx)
        tx_hash = w3.eth.send_raw_transaction(signed.raw_transaction)
        receipt = w3.eth.wait_for_transaction_receipt(tx_hash)

    if receipt.status != 1:
        raise RuntimeError("Transaction reverted on-chain.")

    return _hex0x(receipt.transactionHash)


def _send_revoke_proof(proof_hash_hex: str) -> str:
    if not settings.chain_enabled:
        raise ChainNotConfigured("Chain writes are disabled (CHAIN_ENABLED=false).")

    w3 = _get_w3()
    if not w3.is_connected():
        raise ConnectionError(
            f"Could not reach the local chain at {settings.web3_rpc_url}. "
            "Is `npx hardhat node` running in blockchain/?"
        )

    contract = _get_contract(w3)
    account = w3.eth.account.from_key(settings.web3_private_key)
    proof_bytes = _to_bytes32(proof_hash_hex)

    with _tx_lock:
        nonce = w3.eth.get_transaction_count(account.address, "pending")
        tx = contract.functions.revokeProof(proof_bytes).build_transaction(
            {
                "from": account.address,
                "nonce": nonce,
                "gas": 200_000,
                "gasPrice": w3.eth.gas_price,
            }
        )
        signed = account.sign_transaction(tx)
        tx_hash = w3.eth.send_raw_transaction(signed.raw_transaction)
        receipt = w3.eth.wait_for_transaction_receipt(tx_hash)

    if receipt.status != 1:
        raise RuntimeError("Revoke transaction reverted on-chain.")

    return _hex0x(receipt.transactionHash)


def read_proof_from_chain(proof_hash_hex: str) -> dict:
    """
    Public, unauthenticated read -- no wallet or private key needed, just
    a connection to the chain. Used by GET /verify so a caller can see
    what the blockchain itself says, independent of the database.

    Returns {"reachable": bool, "exists": bool, "event_type": int|None,
    "timestamp": int|None, "revoked": bool|None, "error": str|None}.
    """
    try:
        w3 = _get_w3()
        if not w3.is_connected():
            return {"reachable": False, "exists": False, "error": "chain unreachable"}

        contract = _get_contract(w3)
        proof_bytes = _to_bytes32(proof_hash_hex)
        exists, event_type, timestamp, revoked = contract.functions.verifyProof(proof_bytes).call()
        return {
            "reachable": True,
            "exists": exists,
            "event_type": event_type,
            "timestamp": timestamp,
            "revoked": revoked,
            "error": None,
        }
    except ChainNotConfigured as e:
        return {"reachable": False, "exists": False, "error": str(e)}
    except Exception as e:  # noqa: BLE001 -- this must never bubble into the request path
        return {"reachable": False, "exists": False, "error": str(e)[:300]}


def log_event_in_background(
    proof_hash: str,
    event_type: int,
    *,
    credential_id: str | None = None,
    gate_log_id: str | None = None,
) -> None:
    """
    Entry point for `background_tasks.add_task(...)`. Opens its OWN
    database session rather than reusing the request's -- by the time a
    background task runs, the request-scoped session from `get_db` may
    already be mid-teardown, so sharing it is a footgun. This function
    must never raise: nothing is listening for an exception from a
    background task, so every failure is caught and written onto the
    ChainTransaction row instead.
    """
    from app.database import SessionLocal
    from app import models

    db = SessionLocal()
    try:
        chain_tx = models.ChainTransaction(
            credential_id=credential_id,
            gate_log_id=gate_log_id,
            proof_hash=proof_hash,
            event_type=event_type,
            status=models.ChainTxStatus.pending,
        )
        db.add(chain_tx)
        db.commit()
        db.refresh(chain_tx)

        try:
            tx_hash = _send_log_proof(proof_hash, event_type)
            chain_tx.tx_hash = tx_hash
            chain_tx.status = models.ChainTxStatus.confirmed
            chain_tx.confirmed_at = datetime.now(timezone.utc)
        except Exception as e:  # noqa: BLE001
            chain_tx.status = models.ChainTxStatus.failed
            chain_tx.error = str(e)[:500]

        db.commit()
    finally:
        db.close()


def log_revoke_in_background(proof_hash: str, *, credential_id: str | None = None) -> None:
    """Same pattern as log_event_in_background, for revocations."""
    from app.database import SessionLocal
    from app import models

    db = SessionLocal()
    try:
        chain_tx = models.ChainTransaction(
            credential_id=credential_id,
            gate_log_id=None,
            proof_hash=proof_hash,
            event_type=models.ChainEventType.credential_revoked.value,
            status=models.ChainTxStatus.pending,
        )
        db.add(chain_tx)
        db.commit()
        db.refresh(chain_tx)

        try:
            tx_hash = _send_revoke_proof(proof_hash)
            chain_tx.tx_hash = tx_hash
            chain_tx.status = models.ChainTxStatus.confirmed
            chain_tx.confirmed_at = datetime.now(timezone.utc)
        except Exception as e:  # noqa: BLE001
            chain_tx.status = models.ChainTxStatus.failed
            chain_tx.error = str(e)[:500]

        db.commit()
    finally:
        db.close()
