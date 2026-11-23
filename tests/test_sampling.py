import pytest

from app.modules.sampling.plan import allocate, pick


def team(name, joints):
    members = [{'joint':joint, 'alarms':alarms} for joint, alarms in joints]
    return {'name':name, 'joints':members, 'alarms':sum(alarms for _, alarms in joints)}


def draw(client, data):
    return client.post('/api/sampling', json=data)


def test_floor_gives_every_crew_one():
    teams = [team('甲', [('J1',0),('J2',0)]), team('乙', [('J3',5)])]
    assert allocate(teams, 2) == {'甲':1, '乙':1}


def test_alarms_drive_extra_shares():
    teams = [team('甲', [('J1',3),('J2',1),('J3',0)]), team('乙', [('J4',1),('J5',0)]), team('丙', [('J6',0)])]
    assert allocate(teams, 5) == {'甲':3, '乙':1, '丙':1}


def test_share_capped_by_crew_size():
    teams = [team('甲', [('J1',9)]), team('乙', [('J2',0),('J3',0),('J4',0)])]
    assert allocate(teams, 4) == {'甲':1, '乙':3}


def test_zero_alarms_fall_back_to_size():
    teams = [team('甲', [('J1',0)]), team('乙', [('J2',0),('J3',0),('J4',0)])]
    assert allocate(teams, 3) == {'甲':1, '乙':2}


def test_fewer_quotas_than_crews_go_to_most_alarming():
    teams = [team('甲', [('J1',0)]), team('乙', [('J2',2)]), team('丙', [('J3',5)])]
    assert allocate(teams, 2) == {'甲':0, '乙':1, '丙':1}


def test_pick_prefers_alarming_joints_and_stays_stable():
    joints = [{'joint':'J2','alarms':0}, {'joint':'J1','alarms':0}, {'joint':'J3','alarms':2}]
    assert pick(joints, 2) == ['J3', 'J1']


def test_draw_assigns_quota_and_marks_unsampled(client):
    r = draw(client, {'sample':'clean', 'sampling':{'quota':2, 'crews':{'C-1':'甲班','C-2':'甲班','C-3':'乙班'}}})
    assert r.status_code == 201 and r.json['created'] is True
    batch = r.json['batch']
    assert (batch['quota'], batch['allocated']) == (2, 2)
    teams = {t['name']:t for t in batch['teams']}
    assert teams['甲班']['picked'] == ['C-1'] and teams['乙班']['picked'] == ['C-3']
    assert batch['scope'] == ['C-1', 'C-3'] and batch['not_sampled'] == ['C-2']
    states = {row['joint']:row['state'] for row in batch['rows']}
    assert states == {'C-1':'PICKED', 'C-2':'NOT_SAMPLED', 'C-3':'PICKED'}
    assert batch['approved'] is True and batch['blockers'] == []


def test_retry_same_batch_reuses_list_without_new_quota(client):
    payload = {'sample':'clean', 'sampling':{'quota':2, 'crews':{'C-1':'甲班','C-2':'甲班','C-3':'乙班'}}}
    first = draw(client, payload)
    again = draw(client, payload)
    assert (first.status_code, again.status_code, again.json['created']) == (201, 200, False)
    assert first.json['batch'] == again.json['batch']
    assert len(client.get('/api/sampling').json['batches']) == 1
    other = draw(client, {'sample':'clean', 'sampling':{'quota':3, 'crews':{'C-1':'甲班','C-2':'甲班','C-3':'乙班'}}})
    assert other.json['created'] is True and other.json['batch']['batch_id'] != first.json['batch']['batch_id']
    assert len(client.get('/api/sampling').json['batches']) == 2


def test_over_limit_escalates_whole_crew(client):
    crews = {'F-01':'甲班','F-02':'甲班','F-05':'甲班','F-06':'甲班','F-03':'乙班','F-04':'乙班'}
    batch = draw(client, {'sample':'dirty', 'sampling':{'quota':2, 'crews':crews}}).json['batch']
    teams = {t['name']:t for t in batch['teams']}
    assert teams['甲班']['picked'] == ['F-05']
    assert teams['乙班']['picked'] == ['F-03']
    assert batch['escalations'] == [{'crew':'乙班', 'triggers':['F-03'], 'added':['F-04']}]
    assert batch['scope'] == ['F-03', 'F-04', 'F-05']
    states = {row['joint']:row['state'] for row in batch['rows']}
    assert states['F-04'] == 'ESCALATED' and states['F-01'] == 'NOT_SAMPLED'
    assert batch['approved'] is False
    assert batch['blockers'] == ['SAMPLING_OVER_LIMIT', 'SAMPLING_EVIDENCE_MISSING']


def test_unlisted_joints_fall_into_default_crew(client):
    batch = draw(client, {'sample':'clean', 'sampling':{'quota':1, 'crews':{'C-3':'乙班'}}}).json['batch']
    teams = {t['name']:t for t in batch['teams']}
    assert set(teams) == {'乙班', '未分班'}
    assert teams['未分班']['picked'] == ['C-1'] and batch['approved'] is True


def test_certificate_waits_for_final_scope(client):
    inspection = client.post('/api/inspections', json={'sample':'clean'}).json['inspection_id']
    before = client.get('/api/certificate/'+inspection).json
    assert before['approved'] is True and 'sampling' not in before
    draw(client, {'sample':'clean', 'sampling':{'quota':2, 'crews':{'C-1':'甲班','C-2':'甲班','C-3':'乙班'}}})
    after = client.get('/api/certificate/'+inspection).json
    assert after['approved'] is True
    assert after['sampling']['approved'] is True and after['sampling']['not_sampled'] == ['C-2']


def test_certificate_blocked_until_scope_passes(client):
    inspection = client.post('/api/inspections', json={'sample':'dirty'}).json['inspection_id']
    draw(client, {'sample':'dirty', 'sampling':{'quota':1, 'crews':{'F-03':'乙班','F-04':'乙班'}}})
    cert = client.get('/api/certificate/'+inspection).json
    assert cert['approved'] is False and 'SAMPLING_PENDING' in cert['blockers']
    assert cert['sampling']['blockers'] == ['SAMPLING_EVIDENCE_MISSING']


def test_spec_required(client):
    r = client.post('/api/sampling', json={'sample':'clean'})
    assert (r.status_code, r.json['code']) == (400, 'SAMPLING_SPEC_REQUIRED')


@pytest.mark.parametrize('quota', [0, -1, 'x', 1.5, True])
def test_bad_quota(client, quota):
    r = client.post('/api/sampling', json={'sample':'clean', 'sampling':{'quota':quota}})
    assert (r.status_code, r.json['code']) == (422, 'BAD_QUOTA')


def test_unknown_joint_rejected(client):
    r = client.post('/api/sampling', json={'sample':'clean', 'sampling':{'quota':1, 'crews':{'C-9':'甲班'}}})
    assert (r.status_code, r.json['code']) == (422, 'UNKNOWN_JOINT')


def test_bad_crews_rejected(client):
    r = client.post('/api/sampling', json={'sample':'clean', 'sampling':{'quota':1, 'crews':{'C-1':'  '}}})
    assert (r.status_code, r.json['code']) == (422, 'BAD_CREWS')


def test_unknown_batch_returns_404(client):
    r = client.get('/api/sampling/nope')
    assert (r.status_code, r.json['code']) == (404, 'BATCH_NOT_FOUND')


def test_sampling_page_renders_and_draws(client):
    page = client.get('/inspect/sampling')
    assert page.status_code == 200 and '交工班组抽验'.encode() in page.data and '抽验参数'.encode() in page.data
    r = client.post('/inspect/sampling', data={'sample':'clean', 'quota':'2', 'crews':'C-1,甲班\nC-2,甲班\nC-3,乙班'})
    assert r.status_code == 200 and '复测名单'.encode() in r.data and '甲班'.encode() in r.data
    assert '未抽验'.encode() in r.data


def test_bad_crew_line_shows_error(client):
    r = client.post('/inspect/sampling', data={'sample':'clean', 'quota':'2', 'crews':'C-1'})
    assert r.status_code == 200 and b'BAD_CREW_LINE' in r.data
