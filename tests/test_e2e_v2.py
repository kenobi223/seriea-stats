"""Test end-to-end: /opencode -> approve -> push. NO double git_push."""
import sys, os, time, hashlib, subprocess
sys.path.insert(0, '.')
os.environ.setdefault('DATA_SOURCE_ORDER', 'espn')
os.environ.setdefault('TELEGRAM_OWNER_IDS', '1694501243')

from app import maintenance as m

# 1. Reset stato
state = m._read()
state['pending_proposal'] = None
state['pending_fix'] = False
m._write(state)
print('1. Stato pulito')

# 2. Simula /opencode service worker
req = 'service worker'
proposal_id = hashlib.md5(req.encode()).hexdigest()[:8]
proposal = {
    'id': proposal_id,
    'at': int(time.time()),
    'issues': ['Richiesta diretta da @Ziosapi: ' + req],
    'fixes': [req],
    'news': 'richiesta diretta capo',
    'reason': 'capo ha chiesto: ' + req,
    'status': 'pending',
}
state = m._read()
state['pending_proposal'] = proposal
state['pending_fix'] = True
m._write(state)
print('2. Proposta creata: %s' % proposal_id)

# 3. Verify sw.js content BEFORE approve
sw_before = open('app/web/static/sw.js', encoding='utf-8').read() if os.path.exists('app/web/static/sw.js') else 'NOT EXISTS'
print('3. sw.js prima: %s...' % sw_before[:60])

# 4. approve_pending (chiama _apply_fixes + _git_push internamente)
print('4. Chiamo approve_pending...')
ok, msg = m.approve_pending(proposal_id)
print('   ok=%s, msg=%s' % (ok, msg))

# 5. Verifica sw.js content DOPO approve
sw_after = open('app/web/static/sw.js', encoding='utf-8').read()
print('5. sw.js dopo: %s...' % sw_after[:60])
print('   Contenuto cambiato: %s' % (sw_before != sw_after))

# 6. Verifica stato
state = m._read()
print('6. pending_proposal: %s' % state.get('pending_proposal'))
print('   approved_history: %d entries' % len(state.get('approved_history', [])))

# 7. Verifica git
r = subprocess.run(['git', 'log', '--oneline', '-3'], capture_output=True, text=True, timeout=10)
print('7. Git log:\n%s' % r.stdout)
