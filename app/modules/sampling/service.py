from datetime import datetime, timezone

from app.config import SPEC
from app.errors import InspectionError
from app.modules.archive.identity import canonical, digest
from app.pipeline import run
from .plan import allocate, pick
from .storage import publish

DEFAULT_CREW = '未分班'
ESCALATE_CODES = ('OVER_LIMIT',)


def validate(spec, rows):
    if not isinstance(spec, dict):
        raise InspectionError('SAMPLING_SPEC_REQUIRED', status=400)
    quota = spec.get('quota')
    if type(quota) is not int or quota < 1:
        raise InspectionError('BAD_QUOTA')
    crews = spec.get('crews', {})
    if not isinstance(crews, dict) or any(not isinstance(name, str) or not name.strip() for name in crews.values()):
        raise InspectionError('BAD_CREWS')
    if set(crews) - {row['joint'] for row in rows}:
        raise InspectionError('UNKNOWN_JOINT')
    return quota, {joint: name.strip() for joint, name in crews.items()}


def plan(material, spec):
    results = run(material)
    rows = results['design']['rows']
    if not rows:
        raise InspectionError('EMPTY_DESIGN')
    quota, crews = validate(spec, rows)
    grouped = {}
    for row in rows:
        grouped.setdefault(crews.get(row['joint'], DEFAULT_CREW), []).append(
            {'joint': row['joint'], 'alarms': len(row['near_singles'])})
    teams = [{'name': name, 'joints': sorted(members, key=lambda member: member['joint']),
              'alarms': sum(member['alarms'] for member in members)}
             for name, members in sorted(grouped.items())]
    shares = allocate(teams, quota)
    picked = {team['name']: pick(team['joints'], shares[team['name']]) for team in teams}
    verdict = {row['joint']: row['code'] for row in rows}
    escalations, widened = [], set()
    for team in teams:
        triggers = [joint for joint in picked[team['name']] if verdict[joint] in ESCALATE_CODES]
        if triggers:
            added = [member['joint'] for member in team['joints'] if member['joint'] not in picked[team['name']]]
            widened.update(added)
            escalations.append({'crew': team['name'], 'triggers': triggers, 'added': added})
    chosen = {joint for joints in picked.values() for joint in joints}
    scope = [row['joint'] for row in rows if row['joint'] in chosen | widened]
    state = {joint: 'PICKED' for joint in chosen}
    state.update({joint: 'ESCALATED' for joint in widened})
    batch_rows = [{'joint': row['joint'], 'crew': crews.get(row['joint'], DEFAULT_CREW),
                   'state': state.get(row['joint'], 'NOT_SAMPLED'), 'code': row['code'],
                   'alarms': len(row['near_singles'])} for row in rows]
    scoped = [row for row in batch_rows if row['state'] != 'NOT_SAMPLED']
    blockers = []
    if any(row['code'] == 'OVER_LIMIT' for row in scoped):
        blockers.append('SAMPLING_OVER_LIMIT')
    if any(row['code'] not in ('PASS', 'OVER_LIMIT') for row in scoped):
        blockers.append('SAMPLING_EVIDENCE_MISSING')
    sources = {key: digest(text.encode()) for key, text in material['traces'].items()}
    inspection_id = digest(canonical([SPEC, sources, results['calibration']['settings']]))
    return {'batch_id': digest(canonical([SPEC, 'sampling', inspection_id, quota, crews])),
            'inspection_id': inspection_id, 'rule': SPEC,
            'generated_at': datetime.now(timezone.utc).isoformat(timespec='seconds'),
            'quota': quota, 'allocated': sum(shares.values()), 'crews': crews,
            'teams': [{**team, 'share': shares[team['name']], 'picked': picked[team['name']]} for team in teams],
            'escalations': escalations, 'rows': batch_rows, 'scope': scope, 'scope_count': len(scope),
            'not_sampled': [row['joint'] for row in batch_rows if row['state'] == 'NOT_SAMPLED'],
            'approved': not blockers, 'blockers': blockers}


def draw(database, material, spec):
    return publish(database, plan(material, spec))
