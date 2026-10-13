import unittest
from wallet import create_wallets
from reserves import ReserveLedger


class ReserveLedgerTests(unittest.TestCase):
    def setUp(self):
        self.sender, self.recipient, self.reserve = create_wallets()
        self.ledger = ReserveLedger(reserve_agent_address=self.reserve.address)

    def test_onramp_1000(self):
        event = self.ledger.onramp(self.sender.address, 1000)
        self.assertEqual(self.ledger.vault_fiat, 1000)
        self.assertEqual(self.ledger.circulating, 1000)
        self.assertEqual(self.ledger.balances[self.sender.address], 1000)
        self.assertEqual(self.ledger.balances.get(self.recipient.address, 0), 0)
        self.assertEqual(event["minted_mzar"], 1000)
        self.assertEqual(self.ledger.events, [event])
        self.assertTrue(self.ledger.invariant_ok())

    def test_reject_bad_amounts_without_changing_balances(self):
        for amount in (0, -10, 2.5, True, "1000"):
            with self.subTest(amount=amount):
                with self.assertRaises(ValueError):
                    self.ledger.onramp(self.sender.address, amount)
        self.assertEqual(self.ledger.vault_fiat, 0)
        self.assertEqual(self.ledger.circulating, 0)
        self.assertEqual(self.ledger.events, [])
        self.assertTrue(self.ledger.invariant_ok())

    def test_reject_invalid_address(self):
        for address in ("bob", "f" * 39, "g" * 40, ""):
            with self.subTest(address=address):
                with self.assertRaises(ValueError):
                    self.ledger.onramp(address, 1000)
        self.assertEqual(self.ledger.events, [])

    def test_multiple_deposits_preserve_reserves(self):
        self.ledger.onramp(self.sender.address, 1000)
        self.ledger.onramp(self.sender.address, 500)
        self.assertEqual(self.ledger.balances[self.sender.address], 1500)
        self.assertEqual(self.ledger.vault_fiat, 1500)
        self.assertEqual(self.ledger.circulating, 1500)
        self.assertEqual(len(self.ledger.events), 2)
        self.assertTrue(self.ledger.invariant_ok())

    def test_unbalanced_state_detected(self):
        self.ledger.onramp(self.sender.address, 1000)
        self.ledger.vault_fiat -= 1
        self.assertFalse(self.ledger.invariant_ok())
        with self.assertRaises(RuntimeError):
            self.ledger.onramp(self.sender.address, 10)


if __name__ == "__main__":
    unittest.main()
