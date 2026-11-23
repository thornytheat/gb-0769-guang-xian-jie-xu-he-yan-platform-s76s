import re

from flask import Blueprint, abort, current_app, render_template, request

from .config import SOURCES, SPEC
from .errors import InspectionError
from .input import sample
from .modules.archive.service import archive
from .modules.archive.storage import get, recent
from .modules.certificate.service import certify
from .modules.sampling.service import draw
from .modules.sampling.storage import get as get_batch, latest_for_inspection, recent as recent_batches
from .pipeline import run
from .modules.calibration.contract import FIELDS
from .views import CODES, LABELS, STATES, half_mm_metres, metres, trace_frames

console = Blueprint('console', __name__)
console.add_app_template_filter(metres, 'metres')
console.add_app_template_filter(half_mm_metres, 'half_mm_metres')


def material(mode):
    if mode == 'custom':
        return {'traces':{key:request.form.get(key,'') for key in SOURCES},
                'settings':{key:request.form.get(key,'') for key in FIELDS}}
    return sample(mode)


def crews_from_form(text):
    crews = {}
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        parts = re.split(r'[,=，、\t]', line, maxsplit=1)
        if len(parts) != 2 or not all(part.strip() for part in parts):
            raise InspectionError('BAD_CREW_LINE')
        joint, name = (part.strip() for part in parts)
        crews[joint] = name
    return crews


def sampling_form():
    try:
        quota = int(request.form.get('quota', '').strip())
    except ValueError:
        raise InspectionError('BAD_QUOTA') from None
    return {'quota':quota, 'crews':crews_from_form(request.form.get('crews', ''))}


@console.route('/', methods=['GET','POST'])
@console.route('/inspect/<section>', methods=['GET','POST'])
def view(section='design'):
    if section not in LABELS:
        abort(404)
    mode = request.values.get('sample','dirty')
    database = current_app.config['DATABASE']
    evidence, frames, entries, data = None, {}, [], {}
    issued, fresh, error, sources = None, False, None, {}
    try:
        sources = material(mode)
        if section in ('archive','certificate'):
            if section == 'archive' and request.method == 'POST':
                issued, fresh = archive(database, sources)
            entries = recent(database)
            identifier = request.args.get('inspection') or (entries[0]['inspection_id'] if entries else None)
            if section == 'certificate' and identifier:
                evidence = certify(get(database, identifier), latest_for_inspection(database, identifier))
        elif section == 'sampling':
            data = run(sources)
            frames = trace_frames(data['calibration'])
            if request.method == 'POST':
                issued, fresh = draw(database, sources, sampling_form())
            entries = recent_batches(database)
            identifier = request.args.get('batch') or (issued['batch_id'] if issued else None) \
                or (entries[0]['batch_id'] if entries else None)
            if identifier:
                evidence = get_batch(database, identifier)
        else:
            data = run(sources, section)
            if 'calibration' in data:
                frames = trace_frames(data['calibration'])
    except InspectionError as exc:
        error = exc.code
    return render_template('console.html', section=section, labels=LABELS, codes=CODES, states=STATES, spec=SPEC, mode=mode,
                           data=data, frames=frames, error=error, materials=sources, entries=entries,
                           evidence=evidence, issued=issued, fresh=fresh, fields=FIELDS)
