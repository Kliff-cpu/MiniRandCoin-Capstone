import argparse
import hashlib
import json
from pathlib import Path

from blockchain import verify_signed_transfer


BLOCK_FIELDS = {"index", "timestamp", "transactions", "previous_hash", "nonce", "hash"}
HASH_INPUT_FIELDS = ("index", "timestamp", "transactions", "previous_hash", "nonce")


def block_hash(block):
    payload = {key: block[key] for key in HASH_INPUT_FIELDS}
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _hex_hash(value):
    if not isinstance(value, str) or len(value) != 64:
        return False
    try:
        bytes.fromhex(value)
        return True
    except ValueError:
        return False


def verify_exported_chain(blocks, difficulty=2):
    """Verify a serialised blockchain without a live Blockchain or ReserveLedger instance."""
    result = {
        "valid": False,
        "blocks_checked": 0,
        "transactions_checked": 0,
        "tip_hash": None,
        "error": None,
    }

    def fail(message):
        result["error"] = message
        return result

    if type(difficulty) is not int or not 1 <= difficulty <= 5:
        return fail("difficulty must be an integer from 1 to 5")
    if not isinstance(blocks, list) or not blocks:
        return fail("chain must be a non-empty list of blocks")

    seen_ids = set()
    previous_hash = None

    for height, block in enumerate(blocks):
        if not isinstance(block, dict) or set(block) != BLOCK_FIELDS:
            return fail(f"block {height}: unexpected or missing fields")
        if type(block["index"]) is not int or block["index"] != height:
            return fail(f"block {height}: incorrect block index")
        if type(block["timestamp"]) is not int or block["timestamp"] < 0:
            return fail(f"block {height}: invalid timestamp")
        if type(block["nonce"]) is not int or block["nonce"] < 0:
            return fail(f"block {height}: invalid nonce")
        if not isinstance(block["transactions"], list):
            return fail(f"block {height}: transactions must be a list")
        if not _hex_hash(block["previous_hash"]) or not _hex_hash(block["hash"]):
            return fail(f"block {height}: invalid hash format")
        if block_hash(block) != block["hash"]:
            return fail(f"block {height}: stored hash does not match block content")

        if height == 0:
            if (block["timestamp"] != 0 or block["nonce"] != 0
                    or block["previous_hash"] != "0" * 64
                    or block["transactions"]):
                return fail("block 0: genesis does not match the project genesis")
        else:
            if block["previous_hash"] != previous_hash:
                return fail(f"block {height}: previous hash link is incorrect")
            if not block["hash"].startswith("0" * difficulty):
                return fail(f"block {height}: proof-of-work requirement not met")
            if not block["transactions"]:
                return fail(f"block {height}: mined block cannot be empty")

            for tx in block["transactions"]:
                if not verify_signed_transfer(tx):
                    return fail(f"block {height}: invalid signed transfer")
                if tx["id"] in seen_ids:
                    return fail(f"block {height}: duplicate transaction ID")
                seen_ids.add(tx["id"])
                result["transactions_checked"] += 1

        previous_hash = block["hash"]
        result["blocks_checked"] += 1

    result["valid"] = True
    result["tip_hash"] = previous_hash
    return result


def lookup_verified_transaction(blocks, transaction_id, difficulty=2):
    """Return a verified inclusion record, or None if the ID is absent."""
    audit = verify_exported_chain(blocks, difficulty)
    if not audit["valid"]:
        raise ValueError("Cannot trust invalid chain: " + audit["error"])
    if not isinstance(transaction_id, str) or len(transaction_id) != 32:
        return None
    try:
        bytes.fromhex(transaction_id)
    except ValueError:
        return None

    for block in blocks[1:]:
        for tx in block["transactions"]:
            if tx["id"] == transaction_id:
                return {
                    "transaction_id": transaction_id,
                    "sender": tx["sender"],
                    "recipient": tx["recipient"],
                    "amount_mzar": tx["amount"],
                    "block_index": block["index"],
                    "block_hash": block["hash"],
                    "confirmations": len(blocks) - block["index"],
                    "signature_valid": True,
                    "chain_verified": True,
                    "included": True,
                }
    return None


def read_chain_snapshot(path):
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or set(payload) != {"difficulty", "chain"}:
        raise ValueError("Expected snapshot with exactly 'difficulty' and 'chain' fields")
    return payload


def main():
    parser = argparse.ArgumentParser(description="Verify a classroom blockchain snapshot")
    parser.add_argument("snapshot", help="JSON snapshot saved by the notebook")
    parser.add_argument("--txid", help="Optional transaction ID to look up")
    args = parser.parse_args()

    try:
        payload = read_chain_snapshot(args.snapshot)
        report = verify_exported_chain(payload["chain"], payload["difficulty"])
        if args.txid and report["valid"]:
            report["lookup"] = lookup_verified_transaction(
                payload["chain"], args.txid, payload["difficulty"]
            )
        print(json.dumps(report, indent=2))
        return 0 if report["valid"] and (not args.txid or report.get("lookup")) else 1
    except (ValueError, OSError, json.JSONDecodeError) as exc:
        print(json.dumps({"valid": False, "error": str(exc)}, indent=2))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
