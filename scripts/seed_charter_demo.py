"""Build the local demo once, retaining the original preview unchanged."""
from pathlib import Path
import sqlite3
import sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from app.demo_data import seed
original=ROOT/'.local/charterstats-20261107/fleet.sqlite'
backup=ROOT/'.local/charterstats-20261107/before-demo.sqlite'
if not backup.exists():
    with sqlite3.connect(f'file:{original}?mode=ro',uri=True) as source,sqlite3.connect(backup) as target:source.backup(target)
    backup.chmod(0o600)
print(seed(ROOT/'.local/charterstats-demo-20261107',original))
