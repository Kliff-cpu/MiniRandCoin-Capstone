from dataclasses import dataclass, field
from datetime import datetime, timezone
import uuid


@dataclass
class ReserveLedger:
    reserve_agent_address: str
    vault_fiat: int = 0
    circulating: int = 0
    balances: dict[str, int] = field(default_factory=dict)
    events: list[dict] = field(default_factory=list)
    receipts: list[dict] = field(default_factory=list)

    def invariant_ok(self) -> bool:
        return (
            self.vault_fiat >= 0
            and self.circulating >= 0
            and all(type(value) is int and value >= 0 for value in self.balances.values())
            and self.vault_fiat == self.circulating == sum(self.balances.values())
        )

    def onramp(self, address: str, amount: int) -> dict:
        if not isinstance(address, str) or len(address) != 40:
            raise ValueError("address must be a 40-character wallet address")
        try:
            int(address, 16)
        except ValueError as exc:
            raise ValueError("address must be hexadecimal") from exc

        if type(amount) is not int or amount <= 0:
            raise ValueError("deposit amount must be a positive whole local-currency unit")
        if not self.invariant_ok():
            raise RuntimeError("reserve ledger is not balanced before issuance")

        event = {
            "event_id": uuid.uuid4().hex,
            "type": "ON_RAMP",
            "timestamp_utc": datetime.now(timezone.utc).isoformat(),
            "sender_address": address,
            "reserve_agent_address": self.reserve_agent_address,
            "local_currency": "ZAR",
            "deposited_local": amount,
            "stablecoin": "mZAR",
            "minted_mzar": amount,
            "conversion_rate": "1:1",
        }

        self.vault_fiat += amount
        self.circulating += amount
        self.balances[address] = self.balances.get(address, 0) + amount
        self.events.append(event)

        if not self.invariant_ok():
            raise RuntimeError("reserve invariant failed after issuance")

        return event

    def record_confirmed_transfers(
        self, transactions: list[dict], block_index: int, block_hash: str
    ) -> list[dict]:
        if not self.invariant_ok():
            raise RuntimeError("reserve ledger is not balanced before settlement")

        updated = dict(self.balances)
        records = []

        for transaction in transactions:
            sender = transaction["sender"]
            recipient = transaction["recipient"]
            amount = transaction["amount"]

            if type(amount) is not int or amount <= 0:
                raise ValueError("transfer amount must be a positive integer")
            if updated.get(sender, 0) < amount:
                raise ValueError("insufficient balance for confirmed transfer")

            updated[sender] = updated.get(sender, 0) - amount
            updated[recipient] = updated.get(recipient, 0) + amount
            records.append({
                "event_id": uuid.uuid4().hex,
                "type": "TRANSFER_CONFIRMED",
                "transaction_id": transaction["id"],
                "sender_address": sender,
                "recipient_address": recipient,
                "amount_mzar": amount,
                "block_index": block_index,
                "block_hash": block_hash,
            })

        self.balances = updated
        self.events.extend(records)
        if not self.invariant_ok():
            raise RuntimeError("reserve invariant failed after settlement")
        return records

    def record_redemption(
        self,
        *,
        redemption_id: str,
        recipient_address: str,
        amount: int,
        reference_transaction_id: str,
        block_index: int,
        block_hash: str,
        confirmations: int,
    ) -> dict:
        if not self.invariant_ok():
            raise RuntimeError("reserve ledger invariant is broken")
        if type(amount) is not int or amount <= 0:
            raise ValueError("redemption amount must be a positive whole mZAR unit")
        if any(item["redemption_id"] == redemption_id for item in self.receipts):
            raise ValueError("redemption request has already been processed")

        recorded = [
            event for event in self.events
            if event["type"] == "TRANSFER_CONFIRMED"
            and event["transaction_id"] == reference_transaction_id
            and event["recipient_address"] == recipient_address
            and event["block_index"] == block_index
            and event["block_hash"] == block_hash
        ]
        if len(recorded) != 1:
            raise ValueError("no matching confirmed transfer event")

        previously_redeemed = sum(
            item["burned_mzar"] for item in self.receipts
            if item["reference_transaction_id"] == reference_transaction_id
        )
        if previously_redeemed + amount > recorded[0]["amount_mzar"]:
            raise ValueError("amount exceeds unredeemed funds from this transfer")
        if self.balances.get(recipient_address, 0) < amount:
            raise ValueError("insufficient mZAR balance for redemption")
        if self.vault_fiat < amount or self.circulating < amount:
            raise ValueError("insufficient reserves or outstanding supply")

        receipt = {
            "receipt_id": uuid.uuid4().hex,
            "redemption_id": redemption_id,
            "type": "OFF_RAMP",
            "timestamp_utc": datetime.now(timezone.utc).isoformat(),
            "recipient_address": recipient_address,
            "reference_transaction_id": reference_transaction_id,
            "confirmed_block_index": block_index,
            "confirmed_block_hash": block_hash,
            "confirmation_depth_at_payout": confirmations,
            "stablecoin": "mZAR",
            "burned_mzar": amount,
            "local_currency": "ZAR",
            "paid_local": amount,
            "conversion_rate": "1:1",
            "payout_status": "SIMULATED",
            "reserve_after_zar": self.vault_fiat - amount,
            "circulating_after_mzar": self.circulating - amount,
        }

        self.balances[recipient_address] -= amount
        self.circulating -= amount
        self.vault_fiat -= amount
        self.receipts.append(receipt)
        self.events.append(dict(receipt))

        if not self.invariant_ok():
            raise RuntimeError("reserve ledger invariant failed after redemption")
        return dict(receipt)
