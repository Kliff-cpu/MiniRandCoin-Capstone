import argparse
import json
import threading
from pathlib import Path
from urllib.request import urlopen

from api import create_server
from demo import call, run_demo
from verification import lookup_verified_transaction, verify_exported_chain


def execute(port=0, keep_open=False, evidence_dir='evidence'):
    server = create_server(port=port)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f'http://127.0.0.1:{server.server_address[1]}'
    print(f'Local API: {base}')
    try:
        summary = run_demo(base)
        code, chain = call(base, 'GET', '/chain')
        assert code == 200
        code, events = call(base, 'GET', '/events')
        assert code == 200
        code, state = call(base, 'GET', '/state')
        assert code == 200
        code, proof = call(base, 'GET', '/verify/' + summary['transaction_id'])
        assert code == 200

        independent_audit = verify_exported_chain(chain['chain'], chain['difficulty'])
        inclusion = lookup_verified_transaction(chain['chain'], summary['transaction_id'], chain['difficulty'])
        assert independent_audit['valid'] and inclusion['included']

        output_dir = Path(evidence_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
        evidence = {
            'summary': summary,
            'chain': chain,
            'events': events,
            'state': state,
            'verification': proof,
            'independent_chain_audit': independent_audit,
        }
        (output_dir / 'part_a_evidence.json').write_text(
            json.dumps(evidence, indent=2), encoding='utf-8'
        )
        with urlopen(base + '/explorer', timeout=15) as response:
            (output_dir / 'explorer_snapshot.html').write_text(
                response.read().decode('utf-8'), encoding='utf-8'
            )
        with urlopen(base + '/explorer/tx/' + summary['transaction_id'], timeout=15) as response:
            (output_dir / 'transaction_detail_snapshot.html').write_text(
                response.read().decode('utf-8'), encoding='utf-8'
            )
        print('\nINDEPENDENT CHAIN AUDIT PASSED')
        print('Evidence:', output_dir / 'part_a_evidence.json')
        print('Explorer snapshot:', output_dir / 'explorer_snapshot.html')
        if keep_open:
            print('Live explorer:', base + '/explorer')
            print('Press Ctrl+C after presenting.')
            try:
                while True:
                    thread.join(0.5)
            except KeyboardInterrupt:
                pass
        return evidence
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def main():
    parser = argparse.ArgumentParser(description='Run the complete MiniRandCoin capstone demonstration')
    parser.add_argument('--port', type=int, default=0, help='0 selects a free localhost port')
    parser.add_argument('--keep-open', action='store_true', help='keep explorer available until Ctrl+C')
    parser.add_argument('--evidence-dir', default='evidence')
    args = parser.parse_args()
    execute(port=args.port, keep_open=args.keep_open, evidence_dir=args.evidence_dir)


if __name__ == '__main__':
    main()
