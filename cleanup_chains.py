import sqlite3, sys, importlib.util

# Load chains.py directly to avoid triggering prospecting/__init__.py
# (which would cascade-import scorer/scraper and fail outside the container env)
spec = importlib.util.spec_from_file_location(
    "chains", "/opt/curbsite-sales-agent/src/prospecting/chains.py"
)
_chains_mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(_chains_mod)
is_chain = _chains_mod.is_chain

db = sqlite3.connect('data/leads/leads.db')
c = db.cursor()
c.execute('SELECT id, business_name FROM leads')
rows = c.fetchall()

disqualified = []
for row_id, name in rows:
    if name and is_chain(name):
        disqualified.append((row_id, name))

print(f'Found {len(disqualified)} chain leads to disqualify:')
for row_id, name in disqualified:
    print(f'  {row_id}: {name}')
    c.execute('UPDATE leads SET status="disqualified", notes="chain/franchise" WHERE id=?', (row_id,))

db.commit()
print(f'Done. {len(disqualified)} leads disqualified.')
db.close()
