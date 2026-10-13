import json
import threading
import unittest
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from api import create_server
from blockchain import create_signed_transfer
from redemption import create_signed_redemption
from wallet import Wallet


class PaymentAPITests(unittest.TestCase):
    def setUp(self):
        self.server = create_server(port=0)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base = f"http://127.0.0.1:{self.server.server_address[1]}"
        self.sender = Wallet("Sender")
        self.recipient = Wallet("Recipient")

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=3)

    def request(self, method, path, body=None, raw=False):
        payload = body if raw else (json.dumps(body).encode() if body is not None else None)
        req = Request(self.base + path, data=payload, method=method,
                      headers={"Content-Type": "application/json"})
        try:
            with urlopen(req, timeout=10) as response:
                return response.status, json.load(response)
        except HTTPError as exc:
            return exc.code, json.loads(exc.read().decode("utf-8"))

    def deposit(self):
        return self.request("POST", "/onramp", {"address": self.sender.address, "amount": 1000})

    def test_initial_state_and_wallet_metadata(self):
        self.assertEqual(self.request("GET", "/health")[0], 200)
        status, state = self.request("GET", "/state")
        self.assertEqual(status, 200)
        self.assertTrue(state["reserve_invariant_ok"])
        self.assertEqual(state["vault_reserves_zar"], 0)
        status, agent = self.request("GET", "/reserve-agent")
        self.assertEqual(status, 200)
        self.assertNotIn("private_key", agent)
        self.assertNotIn("_private_key", agent)

    def test_onramp_and_event(self):
        status, output = self.deposit()
        self.assertEqual(status, 201)
        self.assertEqual(output["event"]["minted_mzar"], 1000)
        self.assertEqual(output["state"]["circulating_mzar"], 1000)
        self.assertEqual(self.request("GET", "/events")[0], 200)

    def test_signed_payment_and_mining(self):
        self.deposit()
        tx = create_signed_transfer(self.sender, self.recipient.address, 750)
        self.assertEqual(self.request("POST", "/transactions/new", tx)[0], 202)
        self.assertEqual(self.request("GET", "/verify/" + tx["id"])[0], 404)
        code, mined = self.request("POST", "/mine")
        self.assertEqual(code, 201)
        self.assertTrue(mined["block"]["hash"].startswith("00"))
        self.assertTrue(mined["chain_valid"])
        self.assertEqual(self.request("GET", "/transactions/" + tx["id"])[0], 200)
        code, verified = self.request("GET", "/verify/" + tx["id"])
        self.assertEqual(code, 200)
        self.assertTrue(verified["included"])

    def test_signed_redemption_and_duplicate_rejection(self):
        self.deposit()
        tx = create_signed_transfer(self.sender, self.recipient.address, 750)
        self.request("POST", "/transactions/new", tx)
        self.request("POST", "/mine")
        redemption = create_signed_redemption(self.recipient, tx["id"], 750)
        code, payout = self.request("POST", "/offramp", redemption)
        self.assertEqual(code, 201)
        self.assertEqual(payout["receipt"]["paid_local"], 750)
        self.assertEqual(self.request("POST", "/offramp", redemption)[0], 400)
        state = self.request("GET", "/state")[1]
        self.assertEqual(state["vault_reserves_zar"], 250)
        self.assertEqual(state["circulating_mzar"], 250)

    def test_insufficient_balance_and_bad_signature(self):
        self.deposit()
        tx = create_signed_transfer(self.sender, self.recipient.address, 750)
        tx["amount"] = 749
        self.assertEqual(self.request("POST", "/transactions/new", tx)[0], 400)
        tx = create_signed_transfer(self.sender, self.recipient.address, 1001)
        self.assertEqual(self.request("POST", "/transactions/new", tx)[0], 400)
        state = self.request("GET", "/state")[1]
        self.assertEqual(state["balances_mzar"][self.sender.address], 1000)

    def test_bad_json_object_types_return_400(self):
        for endpoint in ("/onramp", "/transactions/new", "/offramp"):
            for payload in ([1], "hello", None):
                self.assertEqual(self.request("POST", endpoint, payload)[0], 400)
        self.assertEqual(self.request("POST", "/onramp", b"{", raw=True)[0], 400)

    def test_rejected_invalid_amounts(self):
        for amount in (-2, True, 0, 1.5, "1000"):
            self.assertEqual(self.request("POST", "/onramp", {
                "address": self.sender.address, "amount": amount})[0], 400)
        self.assertEqual(self.request("GET", "/state")[1]["circulating_mzar"], 0)

    def test_missing_routes_and_empty_mining(self):
        self.assertEqual(self.request("POST", "/mine")[0], 400)
        self.assertEqual(self.request("GET", "/verify/unknown")[0], 404)
        self.assertEqual(self.request("GET", "/unknown")[0], 404)
        self.assertEqual(self.request("POST", "/unknown", {})[0], 404)


if __name__ == "__main__":
    unittest.main()
