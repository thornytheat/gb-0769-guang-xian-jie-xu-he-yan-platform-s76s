import json
import sqlite3
from contextlib import closing, contextmanager
from pathlib import Path

from app.errors import InspectionError
from app.modules.archive.identity import canonical


@contextmanager
def session(database):
    Path(database).parent.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(database, timeout=15)) as connection, connection:
        connection.execute('CREATE TABLE IF NOT EXISTS samplings '
                           '(id TEXT UNIQUE NOT NULL, inspection_id TEXT NOT NULL, document BLOB NOT NULL)')
        yield connection


def publish(database, batch):
    with session(database) as db:
        key = batch['batch_id']
        changed = db.execute('INSERT INTO samplings VALUES (?, ?, ?) ON CONFLICT(id) DO NOTHING',
                             (key, batch['inspection_id'], canonical(batch))).rowcount
        original = db.execute('SELECT document FROM samplings WHERE id=?', (key,)).fetchone()[0]
        return json.loads(original), changed == 1


def get(database, identifier):
    with session(database) as db:
        record = db.execute('SELECT document FROM samplings WHERE id=?', (identifier,)).fetchone()
        if not record:
            raise InspectionError('BATCH_NOT_FOUND', status=404)
        return json.loads(record[0])


def recent(database):
    with session(database) as db:
        rows = (json.loads(data) for data, in db.execute('SELECT document FROM samplings ORDER BY rowid DESC LIMIT 50'))
        keys = ('batch_id', 'inspection_id', 'generated_at', 'quota', 'allocated', 'scope_count', 'approved')
        return [{key: row[key] for key in keys} for row in rows]


def latest_for_inspection(database, inspection_id):
    with session(database) as db:
        record = db.execute('SELECT document FROM samplings WHERE inspection_id=? ORDER BY rowid DESC LIMIT 1',
                            (inspection_id,)).fetchone()
        return json.loads(record[0]) if record else None
