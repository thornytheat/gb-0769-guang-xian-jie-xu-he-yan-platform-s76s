from app.modules.archive.identity import canonical, digest


def certify(record, batch=None):
    stages = record['computed']
    design = stages['design']
    blockers = []
    if design['missing']:
        blockers.append('MISSING_JOINTS')
    if design['over_limit']:
        blockers.append('LOSS_OVER_LIMIT')
    if not design['design_count']:
        blockers.append('EMPTY_DESIGN')
    if any(line['source'] == 'design' and line['code'] != 'DUPLICATE_EVENT' for line in stages['trace']['isolated']):
        blockers.append('UNVERIFIED_DESIGN_ROWS')
    result = {'inspection_id':record['inspection_id'], 'blockers':blockers,
              'integrity_sha256':digest(canonical(record)), 'record':record}
    if batch is not None:
        result['sampling'] = {'batch_id':batch['batch_id'], 'approved':batch['approved'],
                              'scope':batch['scope'], 'not_sampled':batch['not_sampled'],
                              'blockers':batch['blockers']}
        if not batch['approved']:
            blockers.append('SAMPLING_PENDING')
    result['approved'] = not blockers
    return result
