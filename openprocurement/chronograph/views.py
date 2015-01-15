from pyramid.view import view_config
from openprocurement.chronograph.scheduler import resync_tender, resync_tenders


@view_config(route_name='home', renderer='json')
def my_view(request):
    return {'jobs': dict([
        (i.id, i.next_run_time.isoformat())
        for i in request.registry.scheduler.get_jobs()
    ])}


@view_config(route_name='resync_all', renderer='json')
def resync_all(request):
    url = request.params.get('url', '')
    if not url:
        url = request.registry.api_url + 'tenders'
    resync_tenders(request.registry.scheduler,
                   url,
                   request.registry.api_token,
                   request.registry.callback_url)


@view_config(route_name='resync', renderer='json')
def resync(request):
    tid = request.matchdict['tender_id']
    resync_tender(request.registry.scheduler,
                  request.registry.api_url + 'tenders/' + tid,
                  request.registry.api_token,
                  request.registry.callback_url + 'resync/' + tid,
                  request.registry.db)
