from flask import Blueprint, current_app, jsonify, request

from .errors import InspectionError
from .input import material_from, request_material
from .modules.archive.service import archive
from .modules.archive.storage import get, recent
from .modules.certificate.service import certify
from .modules.sampling.service import draw
from .modules.sampling.storage import get as get_batch, latest_for_inspection, recent as recent_batches
from .pipeline import run

api = Blueprint('fiber_api', __name__, url_prefix='/api')


def calculate(stage):
    return run(request_material(), stage)[stage]


@api.post('/trace')
def trace():
    return calculate('trace')


@api.post('/calibration')
def calibration():
    return calculate('calibration')


@api.post('/pairs')
def pairs():
    return calculate('pairs')


@api.post('/loss')
def loss():
    return calculate('loss')


@api.post('/design')
def design():
    return calculate('design')


@api.post('/inspections')
def submit():
    report, fresh = archive(current_app.config['DATABASE'], request_material())
    return {'inspection_id':report['inspection_id'], 'created':fresh, 'record':report}, 201 if fresh else 200


@api.get('/inspections')
def list_inspections():
    return {'inspections':recent(current_app.config['DATABASE'])}


@api.get('/inspections/<identifier>')
def inspection(identifier):
    return get(current_app.config['DATABASE'], identifier)


@api.post('/sampling')
def sampling():
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        raise InspectionError('JSON_OBJECT_REQUIRED', status=400)
    body = dict(body)
    spec = body.pop('sampling', None)
    batch, fresh = draw(current_app.config['DATABASE'], material_from(body), spec)
    return {'batch_id':batch['batch_id'], 'created':fresh, 'batch':batch}, 201 if fresh else 200


@api.get('/sampling')
def list_batches():
    return {'batches':recent_batches(current_app.config['DATABASE'])}


@api.get('/sampling/<identifier>')
def sampling_batch(identifier):
    return get_batch(current_app.config['DATABASE'], identifier)


@api.get('/certificate/<identifier>')
def certificate(identifier):
    record = inspection(identifier)
    return certify(record, latest_for_inspection(current_app.config['DATABASE'], record['inspection_id']))


@api.get('/export/<identifier>')
def export(identifier):
    response = jsonify(certificate(identifier))
    response.headers['Content-Disposition'] = f'attachment; filename="splice-{identifier[:12]}.json"'
    return response
