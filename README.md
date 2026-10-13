# Assignment 9 — Part A integrated capstone demonstration

This package combines Parts A(a)–A(g). The demo uses **simulated** local currency (ZAR), an mZAR token with a 1:1 simulated reserve rule, signed transfers, local proof-of-work mining, an HTTP API and an explorer.

## Quick start (one command)

Open a terminal in this extracted folder:

```powershell
python -m pip install -r requirements.txt
python integrated_demo.py --keep-open
```

The script starts a localhost server, runs the complete demo automatically, saves the results in `evidence/`, and displays a link to the live explorer. Open the printed address in a browser while the terminal remains running. Press Ctrl+C to stop the server after presenting. `--port 5055` uses a fixed port; the default selects a free local port automatically.

For a one-off run that exits without waiting for the browser:

```powershell
python integrated_demo.py
```

## Jupyter notebook with real outputs

Open `A9_Part_A_Complete_Demonstration.ipynb`. It already includes outputs recorded during an actual successful execution. To reproduce them, select **Kernel > Restart & Run All**. Keep the `.ipynb` and source `.py` files together. A notebook rerun starts its own temporary localhost server and stops that server at the end. The generated hashes, transaction IDs, wallet addresses and nonces will differ each time.

## Full payment example

| Step | Expected change |
|---|---|
| Create Sender, Recipient and Reserve Agent wallets | Fresh ECDSA secp256k1 key pairs |
| Simulate R1,000 on-ramp | Mint 1,000 mZAR; recorded reserve event |
| Submit signed payment of 750 mZAR | Transaction pending; balances unchanged |
| Mine block | Signed transfer confirmed in one proof-of-work block |
| Verify transaction inclusion | Hash links, proof-of-work and signatures checked |
| Simulate off-ramp of 750 mZAR | Recipient gets a simulated R750 payout receipt |
| Check final accounting | Sender 250 mZAR; recipient 0 mZAR; reserves R250; supply 250 mZAR |
| Try invalid payment or repeated redemption | HTTP 400; no unauthorised balance change |

## Automated tests

```powershell
python -m unittest discover -p "test_*.py" -v
```

63 tests passed in the delivered execution environment: 58 earlier tests plus 5 integration tests. Check them again in your local environment before presenting.

## Files

- `A9_Part_A_Complete_Demonstration.ipynb`: executed, step-by-step combined Part A
- `integrated_demo.py`: single-command live demo, prints results and saves evidence
- `demo.py`: original HTTP demonstration helper
- `wallet.py`: secp256k1 key generation and ECDSA signatures
- `reserves.py`: 1:1 reserve-ledger accounting and on-ramp events
- `blockchain.py`: signed transfers, pending pool, PoW blocks and validation
- `redemption.py`: signed off-ramp request and simulated payout receipts
- `verification.py`: independent chain and transaction inclusion checks
- `api.py`: localhost HTTP API and component orchestration
- `explorer.py`: HTML explorer and transaction detail view
- `test_*.py`: automated unit, API and full-flow tests
- `evidence/`: genuine API JSON results and HTML pages from executed runs

## API routes

| Method | Route | Purpose |
|---|---|---|
| GET | `/health` | Server status |
| GET | `/reserve-agent` | Public reserve-agent wallet information |
| POST | `/onramp` | Record simulated deposit and mint mZAR |
| POST | `/transactions/new` | Queue a signed mZAR transaction |
| POST | `/mine` | Mine pending transfers |
| GET | `/chain` | Retrieve blockchain |
| GET | `/transactions/<id>` | Retrieve a mined transfer |
| GET | `/verify/<id>` | Independently verify inclusion |
| POST | `/offramp` | Signed redemption and simulated receipt |
| GET | `/receipts/<id>` | Retrieve redemption receipt |
| GET | `/state` | Balances, supply and reserve invariant |
| GET | `/events` | Reserve, settlement and redemption event records |
| GET | `/explorer` | Human-readable last ten blocks and related events |
| GET | `/explorer/tx/<id>` | Human-readable transaction details |

## Important limits

**Only signed transfers are mined into the blockchain.** On-ramp deposits, conversion events and off-ramp receipts are maintained in a *separate in-memory reserve ledger*. They are verifiable as outputs of this local run, not independently proven on a decentralised network. Balances are tracked in that ledger rather than derived independently from an on-chain token contract. The program cannot prove the existence of real fiat backing or make actual bank transfers. It has no real KYC/AML workflow, durable data storage, secure key vault, distributed consensus, or production network security. Keys are regenerated on each run. The server binds only to `127.0.0.1`.
