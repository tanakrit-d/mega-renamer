"""Optional check using read-only mounted /records and /session volumes.

Run only against a signed-in account. Copies its session into the disposable
container; never imports, renames, moves, exports, or deletes cloud nodes.
"""
import json
import shutil
import sqlite3
import sys
from pathlib import Path
sys.path.insert(0, '/app/backend')
import server
from cloud import link_metadata

shutil.copytree('/session/.megaCmd', '/home/app/.megaCmd', dirs_exist_ok=True,
                ignore=shutil.ignore_patterns('*.socket', 'megacmd.socket*', 'lock*'))
storage = server.storage_info(fresh=True)
print('Account storage parsed:', json.dumps(storage))
with sqlite3.connect('file:/records/jobs.sqlite3?mode=ro', uri=True) as connection:
    rows = connection.execute('SELECT body FROM jobs ORDER BY rowid DESC').fetchall()
for row in rows:
    job = json.loads(row[0])
    if job.get('source'):
        metadata = link_metadata(job['source'])
        print('Public-link size inspected:', json.dumps(metadata))
        break
# Verify the rubbish-bin listing contract without deleting any nodes.
nodes = server.parse_nodes(server.command('find', '//bin', '--show-handles'), '//bin', validate_paths=False)
print('Rubbish-bin listing parsed:', len(nodes), 'nodes')
