import threading
import unittest
from urllib.error import HTTPError
from urllib.request import urlopen

from api import create_server
from blockchain import create_signed_transfer
from explorer import _safe, render_explorer
from redemption import create_signed_redemption
from wallet import Wallet


class ExplorerHTTPTests(unittest.TestCase):
    def setUp(self):
        self.server = create_server(port=0)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base = f'http://127.0.0.1:{self.server.server_address[1]}'
        self.sender = Wallet('Sender')
        self.recipient = Wallet('Recipient')

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=3)

    def html(self, route):
        with urlopen(self.base + route, timeout=10) as response:
            return response.status, response.headers, response.read().decode('utf-8')

    def complete_flow(self):
        p = self.server.platform
        p.ledger.onramp(self.sender.address, 1000)
        tx = create_signed_transfer(self.sender, self.recipient.address, 750)
        p.chain.add_transfer(tx)
        block, _ = p.chain.mine_pending()
        receipt = p.redemption.redeem(create_signed_redemption(self.recipient, tx['id'], 750))
        return tx, block, receipt

    def test_explorer_serves_html_on_localhost(self):
        status, headers, html = self.html('/explorer')
        self.assertEqual(status, 200)
        self.assertIn('text/html', headers['Content-Type'])
        self.assertIn('MiniRandCoin Explorer', html)
        self.assertIn('Block #0', html)
        self.assertIn('Reserves', html)

    def test_explorer_shows_mined_transfer_and_receipt(self):
        tx, block, receipt = self.complete_flow()
        status, _, html = self.html('/explorer')
        self.assertEqual(status, 200)
        self.assertIn('Block #1', html)
        self.assertIn(block.hash, html)
        self.assertIn(tx['id'][:17], html)
        self.assertIn('750 mZAR', html)
        self.assertIn('R750 paid (simulated)', html)
        self.assertIn('R250', html)
        self.assertIn('250 mZAR', html)
        self.assertIn(receipt['receipt_id'][:18], html)

    def test_detail_page_contains_transfer_and_links_to_verification(self):
        tx, block, _ = self.complete_flow()
        status, headers, html = self.html('/explorer/tx/' + tx['id'])
        self.assertEqual(status, 200)
        self.assertIn(tx['id'], html)
        self.assertIn(block.hash, html)
        self.assertIn(self.sender.address, html)
        self.assertIn(self.recipient.address, html)
        self.assertIn('Included in verified chain', html)
        self.assertIn('/verify/' + tx['id'], html)

    def test_unknown_transaction_returns_404(self):
        with self.assertRaises(HTTPError) as caught:
            urlopen(self.base + '/explorer/tx/not-found', timeout=10)
        self.assertEqual(caught.exception.code, 404)

    def test_escapes_external_text(self):
        self.assertEqual(_safe('<script>alert("x")</script>'),
                         '&lt;script&gt;alert(&quot;x&quot;)&lt;/script&gt;')
        self.server.platform.ledger.events.append({
            'type': 'ON_RAMP',
            'event_id': '<script>alert(1)</script>',
            'minted_mzar': 0,
        })
        html = render_explorer(self.server.platform)
        self.assertNotIn('<script>', html)
        self.assertIn('&lt;script&gt;', html)

    def test_private_keys_not_exposed(self):
        tx, _, _ = self.complete_flow()
        _, _, html = self.html('/explorer')
        self.assertNotIn('_private_key', html)
        self.assertNotIn('private_key', html)
        self.assertNotIn('-----BEGIN PRIVATE KEY-----', html)
        self.assertIn(tx['id'][:17], html)

    def test_confirmations_equal_chain_depth(self):
        tx, _, _ = self.complete_flow()
        _, _, html = self.html('/explorer/tx/' + tx['id'])
        self.assertIn('<code>1</code>', html)


if __name__ == '__main__':
    unittest.main()
