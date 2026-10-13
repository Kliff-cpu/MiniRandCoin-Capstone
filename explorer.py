from html import escape
from urllib.parse import quote


def _safe(value):
    return escape(str(value), quote=True)


def _short(value, n=14):
    value = str(value)
    return _safe(value if len(value) <= n + 5 else value[:n] + '…' + value[-5:])


def _layout(title, content):
    return f'''<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{_safe(title)} — MiniRandCoin Explorer</title>
<style>
:root {{ color-scheme: light; }}
body {{ font-family: system-ui, -apple-system, Segoe UI, sans-serif; margin:0;
       background:#f7f8f7; color:#222b2a; line-height:1.45; }}
main {{ width:min(1060px, calc(100% - 36px)); margin:34px auto 65px; }}
header {{ background:#193f37; color:white; padding:20px 0; }}
header .inner {{ width:min(1060px, calc(100% - 36px)); margin:auto; }}
header h1 {{ margin:0 0 3px; font-size:24px; }}
header p {{ margin:0; color:#d8e6e0; font-size:14px; }}
a {{ color:#155e51; text-decoration:none; }} a:hover {{ text-decoration:underline; }}
.card {{ background:white; border:1px solid #dee4e0; border-radius:12px;
         padding:21px; margin:16px 0; }}
.metrics {{ display:grid; grid-template-columns:repeat(auto-fit, minmax(155px,1fr)); gap:10px; }}
.metric {{ background:#fff; padding:16px; border:1px solid #dee4e0; border-radius:10px; }}
.metric strong {{ display:block; font-size:22px; margin-top:4px; }}
.small {{ font-size:13px; color:#586661; }}
.tag {{ display:inline-block; background:#d9eee4; color:#1b5945; padding:3px 9px;
        border-radius:20px; font-weight:650; font-size:12px; }}
.warn {{ background:#fff0da; color:#724b14; }}
.error {{ background:#fce8e4; color:#8c2525; }}
code {{ font-family:ui-monospace,SFMono-Regular,Consolas,monospace;
        font-size:12px; word-break:break-all; }}
.tablewrap {{ overflow-x:auto; }}
table {{ width:100%; border-collapse:collapse; font-size:14px; }}
th,td {{ text-align:left; padding:11px 9px; border-bottom:1px solid #e8ede9; vertical-align:top; }}
th {{ color:#56635f; font-size:12px; font-weight:700; }}
h2 {{ margin:0 0 14px; font-size:20px; }}
.block-head {{ display:flex; justify-content:space-between; align-items:center; gap:14px; }}
.detail {{ display:grid; grid-template-columns:160px 1fr; gap:10px;
          padding:10px 0; border-bottom:1px solid #e9edea; }}
.detail .small {{ align-self:start; }}
.note {{ background:#edf3f1; border-left:3px solid #306657; padding:12px 15px; }}
@media (max-width:650px) {{ .detail {{grid-template-columns:1fr; gap:2px;}} }}
</style>
</head>
<body>
<header><div class="inner"><h1>MiniRandCoin Explorer</h1>
<p>Local classroom stablecoin • mZAR • read-only payment audit</p></div></header>
<main><p><a href="/explorer">← All blocks</a> &nbsp;|&nbsp; <a href="/chain">Chain JSON</a>
 &nbsp;|&nbsp; <a href="/state">State JSON</a></p>
{content}
<p class="note small"><strong>Scope:</strong> Mining and signed transfers are blockchain records.
On-ramp deposits and off-ramp receipts are stored in a separate simulated reserve ledger.
This explorer does not prove real fiat custody, independent consensus, or live settlement.</p>
</main></body></html>'''


def _transaction_rows(block, height):
    if not block.transactions:
        return '<p class="small">No transactions (genesis block).</p>'

    parts = ['<div class="tablewrap"><table><thead><tr>'
             '<th>Transaction ID</th><th>From</th><th>To</th>'
             '<th>Amount</th><th>Confirmations</th></tr></thead><tbody>']
    for tx in block.transactions:
        tx_id = str(tx['id'])
        href = '/explorer/tx/' + quote(tx_id, safe='')
        parts.append('<tr>'
                     f'<td><a href="{href}" title="{_safe(tx_id)}"><code>{_short(tx_id, 17)}</code></a></td>'
                     f'<td><code title="{_safe(tx["sender"])}">{_short(tx["sender"], 12)}</code></td>'
                     f'<td><code title="{_safe(tx["recipient"])}">{_short(tx["recipient"], 12)}</code></td>'
                     f'<td><strong>{_safe(tx["amount"])} mZAR</strong></td>'
                     f'<td>{height - block.index + 1}</td></tr>')
    parts.append('</tbody></table></div>')
    return ''.join(parts)


def render_explorer(platform):
    blocks = platform.chain.chain
    state = platform.state()
    height = len(blocks) - 1
    valid = platform.chain.verify_chain()
    chain_tag = '<span class="tag">Verified</span>' if valid else '<span class="tag error">Invalid chain</span>'
    reserve_tag = ('<span class="tag">Balanced</span>' if state['reserve_invariant_ok']
                   else '<span class="tag error">Unbalanced</span>')

    page = ['<h2>Payment overview</h2><div class="metrics">',
            f'<div class="metric"><span class="small">Mined blocks</span><strong>{len(blocks)}</strong></div>',
            f'<div class="metric"><span class="small">Pending transfers</span><strong>{state["pending_transactions"]}</strong></div>',
            f'<div class="metric"><span class="small">Reserves</span><strong>R{state["vault_reserves_zar"]}</strong></div>',
            f'<div class="metric"><span class="small">Circulating supply</span><strong>{state["circulating_mzar"]} mZAR</strong></div>',
            '</div>',
            f'<div class="card"><strong>Chain:</strong> {chain_tag} &nbsp; '
            f'<strong>1:1 reserve rule:</strong> {reserve_tag}</div>']

    page.append('<h2>Recent blocks</h2>')
    for block in reversed(blocks[-10:]):
        page.append('<section class="card">'
                    f'<div class="block-head"><h2>Block #{block.index}</h2>'
                    f'<span class="tag">{len(block.transactions)} transaction(s)</span></div>'
                    f'<div class="small">Block hash</div><code>{_safe(block.hash)}</code>'
                    f'<div class="small" style="margin-top:9px">Previous hash</div>'
                    f'<code>{_safe(block.previous_hash)}</code>'
                    f'<p class="small">Nonce: {_safe(block.nonce)} · Timestamp: {_safe(block.timestamp)}'
                    f' · Confirmations: {height - block.index + 1 if block.index else "Genesis"}</p>'
                    + _transaction_rows(block, height) + '</section>')

    page.append('<section class="card"><h2>Simulated conversion and redemption events</h2>')
    events = platform.ledger.events[-12:]
    if not events:
        page.append('<p class="small">No reserve events recorded yet.</p>')
    else:
        page.append('<div class="tablewrap"><table><thead><tr>'
                    '<th>Event</th><th>Reference</th><th>Amount</th><th>Record</th>'
                    '</tr></thead><tbody>')
        for event in reversed(events):
            kind = event['type']
            if kind == 'ON_RAMP':
                amount = f'{event["minted_mzar"]} mZAR'
                reference = event['event_id']
                location = 'Reserve ledger'
            elif kind == 'OFF_RAMP':
                amount = f'R{event["paid_local"]} paid (simulated)'
                reference = event['receipt_id']
                location = 'Receipt in reserve ledger'
            else:
                amount = f'{event["amount_mzar"]} mZAR'
                reference = event['transaction_id']
                location = f'Block #{event["block_index"]}'
            page.append(f'<tr><td>{_safe(kind)}</td>'
                        f'<td><code title="{_safe(reference)}">{_short(reference, 18)}</code></td>'
                        f'<td>{_safe(amount)}</td><td>{_safe(location)}</td></tr>')
        page.append('</tbody></table></div>')
    page.append('</section>')
    return _layout('All blocks', ''.join(page))


def render_transaction_detail(platform, tx_id):
    item = platform.chain.lookup_transaction(tx_id)
    if item is None:
        return None
    tx = item['transaction']
    valid = platform.chain.verify_chain()
    rows = [
        ('Transaction ID', tx['id']),
        ('Type', tx['type']),
        ('Sender address', tx['sender']),
        ('Recipient address', tx['recipient']),
        ('Amount', f'{tx["amount"]} mZAR'),
        ('Block index', item['block_index']),
        ('Block hash', item['block_hash']),
        ('Confirmations', item['confirmations']),
        ('Signature valid', 'Yes' if valid else 'Chain verification failed'),
        ('Timestamp (UTC)', tx['timestamp_utc']),
    ]
    badge = ('<span class="tag">Included in verified chain</span>' if valid
             else '<span class="tag error">Chain verification failed</span>')
    data = ''.join(f'<div class="detail"><div class="small">{_safe(name)}</div>'
                   f'<code>{_safe(value)}</code></div>' for name, value in rows)
    body = (f'<section class="card"><h2>Transaction details</h2>{badge}{data}'
            f'<p><a href="/verify/{quote(tx_id,safe="")}">Open independent verification JSON →</a></p>'
            '</section>')
    return _layout('Transaction ' + tx_id, body)
