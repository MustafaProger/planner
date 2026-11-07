"""Launch an isolated, offline-provider preview. Never launches the archive loader."""
import json
import os
from pathlib import Path
import shutil
import sqlite3
import sys
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
DEMO = '--demo' in sys.argv
TARGET = ROOT / '.local' / ('charterstats-demo-20261107' if DEMO else 'charterstats-20261107')
TARGET.mkdir(parents=True, exist_ok=True)
os.chmod(TARGET, 0o700)
if DEMO:
    from app.demo_data import seed
    seed(TARGET, ROOT / '.local' / 'charterstats-20261107' / 'fleet.sqlite')
if not DEMO and not (TARGET / 'fleet.sqlite').exists():
    with sqlite3.connect(f'file:{ROOT / "data/fleet.sqlite"}?mode=ro', uri=True) as src, sqlite3.connect(TARGET / 'fleet.sqlite') as dst:
        src.backup(dst)
    # Saved facts only. No provider credentials, sessions, workers or tokens.
    for name in ('monitoring-history.json', 'monitoring-history.sqlite', 'neftm-history.json', 'rosneft-history.json', 'neftm-transactions.json', 'rosneft-transactions.json'):
        source = ROOT / 'data' / name
        if source.exists():
            if source.suffix == '.sqlite':
                with sqlite3.connect(f'file:{source}?mode=ro', uri=True) as src, sqlite3.connect(TARGET / name) as dst:
                    src.backup(dst)
            else:
                shutil.copy2(source, TARGET / name)
os.environ.update(FLEET_DATA=str(TARGET), FLEET_SCHEDULER='disabled', FLEET_LOCAL_PREVIEW='1', PORT='8776', FLEET_ALLOW_BOOTSTRAP='1')
os.environ['FLEET_DEMO'] = '1' if DEMO else '0'
from app import server
from waitress import serve
server.init()
print('CharterStats preview: http://127.0.0.1:8776/charter/overview', flush=True)
serve(server.app, host='127.0.0.1', port=8776, threads=6)
