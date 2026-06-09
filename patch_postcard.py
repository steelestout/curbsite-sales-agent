"""Patch postcard.py to add from_address to the Lob API call."""
path = "/opt/curbsite-sales-agent/src/outreach/postcard.py"

with open(path) as f:
    src = f.read()

# The return address block to insert — uses **{"from": ...} to avoid
# the Python keyword clash with 'from'
FROM_BLOCK = '''        **{"from": {
            "name": "Steele Stout",
            "address_line1": "2717 Rockford Ln",
            "address_city": "Kokomo",
            "address_state": "IN",
            "address_zip": "46902",
            "address_country": "US",
        }},
'''

target = '        front=front,'
if FROM_BLOCK.strip() in src:
    print("from address already present — no change needed")
elif target not in src:
    print(f"ERROR: could not find insertion point: {target!r}")
    raise SystemExit(1)
else:
    patched = src.replace(target, FROM_BLOCK + target, 1)
    with open(path, "w") as f:
        f.write(patched)
    print("postcard.py patched — from_address added")

# Verify
import subprocess
result = subprocess.run(
    ["grep", "-n", "Steele Stout\|Rockford\|Kokomo\|46902\|from_address\|\"from\""],
    capture_output=True, text=True, cwd="/opt/curbsite-sales-agent",
    input=open(path).read()
)
# Just grep the file directly
import os
for i, line in enumerate(open(path), 1):
    if any(kw in line for kw in ["Steele Stout", "Rockford", "Kokomo", "46902", '"from"']):
        print(f"  {i}: {line}", end="")
