import os
from datetime import datetime
from pytz import timezone

TZ = timezone(os.environ['TZ'] if 'TZ' in os.environ else 'Europe/Kiev')


def add_logging_context(event):
    request = event.request
    params = {
        'TENDERS_API_URL': request.registry.api_url,
        'TAGS': 'python,chronograph',
        'CURRENT_URL': request.url,
        'CURRENT_PATH': request.path_info,
        'REMOTE_ADDR': request.remote_addr or '',
        'USER_AGENT': request.user_agent or '',
        'TENDER_ID': '',
        'TIMESTAMP': datetime.now(TZ).isoformat(),
        'REQUEST_ID': request.environ.get('REQUEST_ID', ''),
        'CLIENT_REQUEST_ID': request.headers.get('X-Client-Request-ID', ''),
    }
    if request.params:
        params['PARAMS'] = str(dict(request.params))
    if request.matchdict:
        for i, j in request.matchdict.items():
            params[i.upper()] = j

    request.logging_context = params


def update_logging_context(request, params):
    if not request.__dict__.get('logging_context'):
        request.logging_context = {}

    for x, j in params.items():
        request.logging_context[x.upper()] = j


def context_unpack(request, msg, params=None):
    if params:
        update_logging_context(request, params)
    logging_context = request.logging_context
    journal_context = msg
    for key, value in logging_context.items():
        journal_context["JOURNAL_" + key] = value
    return journal_context
