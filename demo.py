import argparse
import json
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from blockchain import create_signed_transfer
from redemption import create_signed_redemption
from wallet import Wallet


def call(base, method, route, payload=None):
    body = None if payload is None else json.dumps(payload).encode("utf-8")
    request = Request(base + route, data=body, method=method,
                      headers={"Content-Type": "application/json"})
    try:
        with urlopen(request, timeout=20) as response:
            return response.status, json.load(response)
    except HTTPError as exc:
        return exc.code, json.loads(exc.read().decode("utf-8"))


def require(base, method, route, payload, expected):
    code, result = call(base, method, route, payload)
    if code != expected:
        raise AssertionError(f"{method} {route}: expected {expected}, got {code}: {result}")
    print(f"{method:4} {route:30} HTTP {code}")
    return result


def run_demo(base):
    sender = Wallet("Sender")
    recipient = Wallet("Recipient")
    require(base, "GET", "/health", None, 200)
    require(base, "GET", "/reserve-agent", None, 200)

    deposit = require(base, "POST", "/onramp", {"address": sender.address, "amount": 1000}, 201)
    assert deposit["event"]["minted_mzar"] == 1000

    bad = create_signed_transfer(sender, recipient.address, 750)
    bad["amount"] = 751
    require(base, "POST", "/transactions/new", bad, 400)
    too_much = create_signed_transfer(sender, recipient.address, 2000)
    require(base, "POST", "/transactions/new", too_much, 400)

    transfer = create_signed_transfer(sender, recipient.address, 750)
    pending = require(base, "POST", "/transactions/new", transfer, 202)
    assert pending["transaction_id"] == transfer["id"]
    require(base, "GET", "/verify/" + transfer["id"], None, 404)
    mined = require(base, "POST", "/mine", None, 201)
    assert mined["chain_valid"] is True
    assert mined["block"]["hash"].startswith("00")

    found = require(base, "GET", "/transactions/" + transfer["id"], None, 200)
    verification = require(base, "GET", "/verify/" + transfer["id"], None, 200)
    assert found["block_hash"] == verification["block_hash"]
    assert verification["signature_valid"] and verification["chain_verified"]

    request = create_signed_redemption(recipient, transfer["id"], 750)
    redeemed = require(base, "POST", "/offramp", request, 201)
    receipt_id = redeemed["receipt"]["receipt_id"]
    require(base, "GET", "/receipts/" + receipt_id, None, 200)
    require(base, "POST", "/offramp", request, 400)

    chain = require(base, "GET", "/chain", None, 200)
    events = require(base, "GET", "/events", None, 200)
    state = require(base, "GET", "/state", None, 200)
    with urlopen(base + "/explorer", timeout=20) as page:
        explorer_html = page.read().decode("utf-8")
        assert page.status == 200 and "MiniRandCoin Explorer" in explorer_html
        assert "750 mZAR" in explorer_html and "Block #1" in explorer_html
    with urlopen(base + "/explorer/tx/" + transfer["id"], timeout=20) as page:
        detail_html = page.read().decode("utf-8")
        assert transfer["id"] in detail_html and mined["block"]["hash"] in detail_html
    print("GET  /explorer                      HTTP 200")
    print("GET  /explorer/tx/<id>              HTTP 200")

    assert chain["verified"] and chain["length"] == 2
    assert state["balances_mzar"][sender.address] == 250
    assert state["balances_mzar"][recipient.address] == 0
    assert state["vault_reserves_zar"] == state["circulating_mzar"] == 250
    assert state["reserve_invariant_ok"]
    assert len(events["events"]) >= 3

    summary = {
        "sender_address": sender.address,
        "recipient_address": recipient.address,
        "onramp_event_id": deposit["event"]["event_id"],
        "transaction_id": transfer["id"],
        "block_hash": mined["block"]["hash"],
        "mining_attempts": mined["attempts"],
        "inclusion_verified": verification["included"],
        "redemption_receipt_id": receipt_id,
        "payout_status": redeemed["receipt"]["payout_status"],
        "sender_balance_mzar": state["balances_mzar"][sender.address],
        "recipient_balance_mzar": state["balances_mzar"][recipient.address],
        "reserves_zar": state["vault_reserves_zar"],
        "supply_mzar": state["circulating_mzar"],
        "explorer_url": base + "/explorer",
        "transaction_detail_url": base + "/explorer/tx/" + transfer["id"],
    }
    print("\nALL PAYMENT API DEMO CHECKS PASSED")
    print(json.dumps(summary, indent=2))
    return summary


def main():
    parser = argparse.ArgumentParser(description="Reproducible end-to-end payment API demo")
    parser.add_argument("--port", type=int, default=5055)
    args = parser.parse_args()
    run_demo(f"http://127.0.0.1:{args.port}")


if __name__ == "__main__":
    main()
