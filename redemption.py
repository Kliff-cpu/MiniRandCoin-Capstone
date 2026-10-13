from datetime import datetime, timezone
import uuid

from blockchain import Blockchain
from wallet import Wallet, address_from_public_key


REDEMPTION_FIELDS = {
    "redemption_id", "type", "address", "amount", "reference_transaction_id",
    "timestamp_utc", "public_key", "signature",
}


def create_signed_redemption(wallet: Wallet, transfer_id: str, amount: int) -> dict:
    if type(amount) is not int or amount <= 0:
        raise ValueError("redemption amount must be a positive whole mZAR unit")
    if not isinstance(transfer_id, str) or len(transfer_id) != 32:
        raise ValueError("a confirmed transaction ID is required")
    try:
        bytes.fromhex(transfer_id)
    except ValueError as exc:
        raise ValueError("transaction ID must be hexadecimal") from exc

    body = {
        "redemption_id": uuid.uuid4().hex,
        "type": "REDEEM",
        "address": wallet.address,
        "amount": amount,
        "reference_transaction_id": transfer_id,
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "public_key": wallet.public_key_hex,
    }
    return {**body, "signature": wallet.sign_payload(body)}


def verify_signed_redemption(request: dict) -> bool:
    if not isinstance(request, dict) or set(request) != REDEMPTION_FIELDS:
        return False
    if request["type"] != "REDEEM":
        return False
    if type(request["amount"]) is not int or request["amount"] <= 0:
        return False
    for name in ("redemption_id", "reference_transaction_id"):
        value = request[name]
        if not isinstance(value, str) or len(value) != 32:
            return False
        try:
            bytes.fromhex(value)
        except ValueError:
            return False
    if not isinstance(request["timestamp_utc"], str):
        return False
    if not isinstance(request["address"], str):
        return False
    if not isinstance(request["public_key"], str):
        return False
    if not isinstance(request["signature"], str):
        return False

    try:
        expected_address = address_from_public_key(request["public_key"])
    except (ValueError, TypeError):
        return False
    if request["address"] != expected_address:
        return False

    body = {field: value for field, value in request.items() if field != "signature"}
    return Wallet.verify_payload(body, request["signature"], request["public_key"])


class RedemptionService:
    def __init__(self, blockchain: Blockchain, min_confirmations: int = 1):
        if type(min_confirmations) is not int or min_confirmations < 1:
            raise ValueError("min_confirmations must be a positive integer")
        self.blockchain = blockchain
        self.min_confirmations = min_confirmations

    def redeem(self, request: dict) -> dict:
        if not verify_signed_redemption(request):
            raise ValueError("invalid redemption signature or request")
        if not self.blockchain.verify_chain():
            raise ValueError("blockchain verification failed")

        transfer = self.blockchain.lookup_transaction(request["reference_transaction_id"])
        if transfer is None:
            raise ValueError("referenced transfer is not confirmed in the blockchain")
        transaction = transfer["transaction"]
        if transaction["recipient"] != request["address"]:
            raise ValueError("redeeming wallet is not the transfer recipient")
        if transfer["confirmations"] < self.min_confirmations:
            raise ValueError("insufficient blockchain confirmations for redemption")

        return self.blockchain.ledger.record_redemption(
            redemption_id=request["redemption_id"],
            recipient_address=request["address"],
            amount=request["amount"],
            reference_transaction_id=request["reference_transaction_id"],
            block_index=transfer["block_index"],
            block_hash=transfer["block_hash"],
            confirmations=transfer["confirmations"],
        )
