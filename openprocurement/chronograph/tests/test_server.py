from datetime import timedelta
from json import dumps

from bottle import request, response

from openprocurement.chronograph.tests.utils import now, check_status, location_error, resource_partition

API_VERSION = '2.4'
PORT = 6543
API_PATH = '/api/' + API_VERSION + '/{0}'
AUCTIONS_PATH = API_PATH.format('auctions')
SPORE_PATH = API_PATH.format('spore')
RESOURCE_DICT = {
    'auction': {'sublink': 'auctions'},
}


def resource_filter(resource_name):
    regexp = r'{}'.format(RESOURCE_DICT[resource_name]['sublink'])
    return regexp, lambda x: resource_name, lambda x: None


def setup_routing(app, routes=None):
    if routes is None:
        routes = ['spore']
    for route in routes:
        path, method, func = routes_dict[route]
        app.route(path, method, func)


def spore():
    response.set_cookie(
        "SERVER_ID",
        ("a7afc9b1fc79e640f2487ba48243ca071c07a823d278cf9b7adf0fae467a524747"
         "e3c6c6973262130fac2b96a11693fa8bd38623e4daee121f60b4301aef012c"))


def resource_page_get(resource_name):
    if request.params.get('offset'):
        return resource_page(resource_name, request.params.get('offset'))
    resources = {
        "next_page": {
            "path": "/api/2.4/auctions?feed=changes&offset=f547ece35436484e8656a2988fb52a44&mode=_all_&opt_fields=status%2CauctionPeriod%2CprocurementMethodType%2Clots%2Cnext_check",
            "uri": "http://0.0.0.0:6543/api/2.4/auctions?feed=changes&offset=f547ece35436484e8656a2988fb52a44&mode=_all_&opt_fields=status%2CauctionPeriod%2CprocurementMethodType%2Clots%2Cnext_check",
            "offset": "f547ece35436484e8656a2988fb52a44"
        },
        "data": [{
            "status": "active.enquiries",
            "next_check": (now - timedelta(minutes=1)).isoformat(),
            "procurementMethodType": "belowThreshold",
            "dateModified": now.isoformat(),
            "id": "f547ece35436484e8656a2988fb52a44"
        }],
        "prev_page": {
            "path": "/api/2.4/auctions?feed=changes&offset=&mode=_all_&opt_fields=status%2CauctionPeriod%2CprocurementMethodType%2Clots%2Cnext_check",
            "uri": "http://0.0.0.0:6543/api/2.4/auctions?feed=changes&offset=&mode=_all_&opt_fields=status%2CauctionPeriod%2CprocurementMethodType%2Clots%2Cnext_check",
            "offset": ""
        }
    }
    return dumps(resources)


def resource_page(resource_name, resource_id):
    resource = resource_partition(request.app, resource_id, resource_name)
    if not resource:
        return location_error(resource_name)
    return dumps(resource)


def resource_patch(resource_name, resource_id):
    resource = resource_partition(request.app, resource_id, resource_name)
    if not resource:
        return location_error(resource_name)
    if resource_name == 'auction':
        resource['data'] = check_status(resource['data'])
    resource['data'] = _patch(resource['data'], request.json['data'])

    data = dumps(resource, indent=2, separators=(',', ': '))
    request.app.config[resource_name + '_' + resource_id] = data
    return data


def _patch(resource, patch_data):
    for field in patch_data:

        if not resource.get(field):
            resource[field] = patch_data[field]
            continue

        if isinstance(patch_data[field], list):
            for i, object in enumerate(patch_data[field]):
                resource[field][i] = _patch(resource[field][i], object)

        elif isinstance(patch_data[field], dict):
            resource[field] = _patch(resource[field], patch_data[field])

        else:
            resource[field] = patch_data[field]

    return resource


def object_subpage_item_patch(obj_id, subpage_name, subpage_id, resource_name):
    resource = resource_partition(request.app, obj_id, resource_name)
    if subpage_name == 'awards' and request.json['data'].get('status', '') == 'unsuccessful':
        resource['data']['status'] = 'active.awarded'
        resource['data']['next_check'] = (now + timedelta(days=2)).isoformat()
        request.json['data']['complaintPeriod'] = {"endDate": (now + timedelta(days=2)).isoformat()}
    for i, unit in enumerate(resource['data'][subpage_name]):
        if unit.id == subpage_id:
            resource['data'][subpage_name][i].update(request.json['data'])
            response_object = resource['data'][subpage_name][i]
            break
    else:
        return location_error(subpage_name)

    data = dumps(resource, indent=2, separators=(',', ': '))
    request.app.config[resource_name + '_' + obj_id] = data
    return response_object


routes_dict = {
    "spore": (SPORE_PATH, 'HEAD', spore),
    "auctions": (API_PATH.format('<resource_name:resource_filter:auction>'),
                'GET', resource_page_get),
    "auction": (API_PATH.format(
        '<resource_name:resource_filter:auction>') + '/<resource_id>',
        'GET', resource_page),
    "auction_patch": (API_PATH.format('<resource_name:resource_filter:auction>') + "/<resource_id>", 'PATCH', resource_patch),
    "auction_subpage_item_patch": (API_PATH.format('<resource_name:resource_filter:auction>') + '/<obj_id>/<subpage_name>/<subpage_id>', 'PATCH', object_subpage_item_patch),
}
