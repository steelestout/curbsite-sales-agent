import sqlite3, os

db_path = 'data/leads.db'
if not os.path.exists(db_path):
    print(f"DB not found at {db_path}")
    print("Searching for .db files...")
    for root, dirs, files in os.walk('.'):
        for f in files:
            if f.endswith('.db'):
                print(f"  Found: {os.path.join(root, f)}")
else:
    db = sqlite3.connect(db_path)
    tables = [r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")]
    print(f"Tables: {tables}")
    for t in tables:
        cols = [r[1] for r in db.execute(f"PRAGMA table_info({t})")]
        count = db.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
        print(f"  {t}: {count} rows, cols={cols}")
    db.close()
