import argparse
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit

from blockchain import Blockchain
from explorer import render_explorer, render_transaction_detail
from redemption import RedemptionService
from reserves import ReserveLedger
from verification import lookup_verified_transaction, verify_exported_chain
from wallet import Wallet


class PaymentPlatform:
    def __init__(self):
        self.reserve_agent = Wallet("ReserveAgent")
        self.ledger = ReserveLedger(reserve_agent_address=self.reserve_agent.address)
        self.chain = Blockchain(self.ledger, difficulty=2)
        self.redemption = RedemptionService(self.chain, min_confirmations=1)
        self.lock = threading.RLock()

    def state(self):
        return {
            "currency": "mZAR",
            "reserve_currency": "ZAR",
            "exchange_rule": "1:1",
            "vault_reserves_zar": self.ledger.vault_fiat,
            "circulating_mzar": self.ledger.circulating,
            "balances_mzar": dict(self.ledger.balances),
            "reserve_invariant_ok": self.ledger.invariant_ok(),
            "pending_transactions": len(self.chain.pending_transactions),
            "blocks": len(self.chain.chain),
            "conversion_events": sum(e["type"] == "ON_RAMP" for e in self.ledger.events),
            "redemption_receipts": len(self.ledger.receipts),
        }


def reject_invalid_constant(value):
    raise ValueError("Invalid numeric constant")


class PaymentHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = "MiniZAR-Capstone/1.0"

    def log_message(self, format, *args):
        pass

    @property
    def platform(self):
        return self.server.platform

    def respond(self, status, payload):
        content = json.dumps(payload, indent=2, allow_nan=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(content)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(content)

    def respond_html(self, status, markup):
        body = markup.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Content-Security-Policy", "default-src 'none'; style-src 'unsafe-inline'")
        self.end_headers()
        self.wfile.write(body)

    def parse_body(self):
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError as exc:
            raise ValueError("Invalid Content-Length") from exc
        if length <= 0 or length > 65536:
            raise ValueError("JSON request body required (maximum 64 KiB)")
        try:
            data = json.loads(self.rfile.read(length).decode("utf-8"),
                              parse_constant=reject_invalid_constant)
        except (UnicodeError, json.JSONDecodeError) as exc:
            raise ValueError("Invalid JSON request body") from exc
        if not isinstance(data, dict):
            raise ValueError("JSON request body must be an object")
        return data

    def do_GET(self):
        path = urlsplit(self.path).path
        with self.platform.lock:
            if path == "/explorer":
                self.respond_html(200, render_explorer(self.platform))
                return
            if path.startswith("/explorer/tx/"):
                tx_id = path.removeprefix("/explorer/tx/")
                page = render_transaction_detail(self.platform, tx_id)
                if page is None:
                    self.respond(404, {"error": "transaction not found in a mined block"})
                else:
                    self.respond_html(200, page)
                return
            if path == "/health":
                self.respond(200, {"status": "ok", "network": "localhost simulation"})
                return
            if path == "/reserve-agent":
                self.respond(200, self.platform.reserve_agent.public_info())
                return
            if path == "/state":
                self.respond(200, self.platform.state())
                return
            if path == "/chain":
                chain = [block.to_dict() for block in self.platform.chain.chain]
                audit = verify_exported_chain(chain, self.platform.chain.difficulty)
                self.respond(200, {"length": len(chain), "difficulty": self.platform.chain.difficulty,
                                   "verified": audit["valid"], "chain": chain})
                return
            if path == "/events":
                self.respond(200, {"events": list(self.platform.ledger.events)})
                return
            if path.startswith("/transactions/"):
                tx_id = path.removeprefix("/transactions/")
                item = self.platform.chain.lookup_transaction(tx_id)
                if item is None:
                    self.respond(404, {"error": "transaction not found in a mined block"})
                else:
                    self.respond(200, {"transaction_id": tx_id, **item})
                return
            if path.startswith("/verify/"):
                tx_id = path.removeprefix("/verify/")
                blocks = [block.to_dict() for block in self.platform.chain.chain]
                audit = verify_exported_chain(blocks, self.platform.chain.difficulty)
                if not audit["valid"]:
                    self.respond(409, {"error": "chain failed independent verification", "audit": audit})
                    return
                item = lookup_verified_transaction(blocks, tx_id, self.platform.chain.difficulty)
                if item is None:
                    self.respond(404, {"error": "transaction not found in verified chain"})
                else:
                    self.respond(200, item)
                return
            if path.startswith("/receipts/"):
                receipt_id = path.removeprefix("/receipts/")
                item = next((x for x in self.platform.ledger.receipts
                             if x["receipt_id"] == receipt_id), None)
                if item is None:
                    self.respond(404, {"error": "redemption receipt not found"})
                else:
                    self.respond(200, {"receipt": item})
                return
            self.respond(404, {"error": "endpoint not found"})

    def do_POST(self):
        path = urlsplit(self.path).path
        if path not in {"/onramp", "/transactions/new", "/mine", "/offramp"}:
            self.respond(404, {"error": "endpoint not found"})
            return
        try:
            with self.platform.lock:
                if path == "/onramp":
                    data = self.parse_body()
                    if set(data) != {"address", "amount"}:
                        raise ValueError("Expected address and amount")
                    event = self.platform.ledger.onramp(data["address"], data["amount"])
                    self.respond(201, {"event": event, "state": self.platform.state()})
                elif path == "/transactions/new":
                    data = self.parse_body()
                    tx_id = self.platform.chain.add_transfer(data)
                    self.respond(202, {"transaction_id": tx_id, "status": "PENDING",
                                       "pending_count": len(self.platform.chain.pending_transactions)})
                elif path == "/mine":
                    if self.headers.get("Content-Length", "0") not in {"", "0"}:
                        data = self.parse_body()
                        if data:
                            raise ValueError("POST /mine does not accept parameters")
                    block, attempts = self.platform.chain.mine_pending()
                    self.respond(201, {"status": "MINED", "block": block.to_dict(),
                                       "attempts": attempts, "chain_valid": self.platform.chain.verify_chain(),
                                       "state": self.platform.state()})
                elif path == "/offramp":
                    data = self.parse_body()
                    receipt = self.platform.redemption.redeem(data)
                    self.respond(201, {"receipt": receipt, "state": self.platform.state()})
        except ValueError as exc:
            self.respond(400, {"error": str(exc)})
        except RuntimeError as exc:
            self.respond(409, {"error": str(exc)})


def create_server(port=5055, host="127.0.0.1"):
    if host != "127.0.0.1":
        raise ValueError("Classroom server must bind to 127.0.0.1")
    server = ThreadingHTTPServer((host, port), PaymentHandler)
    server.platform = PaymentPlatform()
    return server


def main():
    parser = argparse.ArgumentParser(description="MiniZAR classroom payment API")
    parser.add_argument("--port", type=int, default=5055)
    args = parser.parse_args()
    server = create_server(port=args.port)
    print(f"Payment API: http://127.0.0.1:{server.server_address[1]}", flush=True)
    print(f"Explorer: http://127.0.0.1:{server.server_address[1]}/explorer", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
