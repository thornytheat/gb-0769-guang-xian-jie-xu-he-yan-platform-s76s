from fractions import Fraction


def allocate(teams, quota):
    """初抽名额分配。名额够时每班保底 1 个，余额按单端告警数以 D'Hondt 最大商数法
    追加，商相同按班组名稳定裁决；名额不足班数时告警重的班优先各得 1 个。
    全程确定性，同批重试得到同一份名单，不重复占用名额。"""
    shares = {team['name']: 0 for team in teams}
    size = {team['name']: len(team['joints']) for team in teams}
    weight = {team['name']: team['alarms'] for team in teams}
    if not any(weight.values()):
        weight = dict(size)
    remaining = quota
    if quota >= len(teams):
        for team in teams:
            shares[team['name']] = 1
        remaining -= len(teams)
    else:
        urgent = sorted(teams, key=lambda team: (-weight[team['name']], team['name']))
        for team in urgent[:quota]:
            shares[team['name']] = 1
        remaining = 0
    while remaining > 0:
        open_teams = [team for team in teams if shares[team['name']] < size[team['name']]]
        if not open_teams:
            break
        best = sorted(open_teams, key=lambda team: (Fraction(-weight[team['name']], shares[team['name']] + 1),
                                                    team['name']))[0]
        shares[best['name']] += 1
        remaining -= 1
    return shares


def pick(joints, share):
    """班内定名单：单端告警多的接头先抽，平手按接头号，取前 share 个。"""
    ordered = sorted(joints, key=lambda row: (-row['alarms'], row['joint']))
    return [row['joint'] for row in ordered[:share]]
