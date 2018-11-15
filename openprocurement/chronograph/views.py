from pyramid.view import view_config

from openprocurement.chronograph.constants import STREAMS_KEYS
from openprocurement.chronograph.scheduler import (
    get_calendar,
    recheck_auction,
    resync_auction,
    resync_auctions,
    resync_auctions_back,
)
from openprocurement.chronograph.utils import (
    set_holiday, delete_holiday,
    get_streams, set_streams
)


@view_config(route_name='home', renderer='json')
def home_view(request):
    return {'jobs': dict([
        (i.id, i.next_run_time.isoformat())
        for i in request.registry.scheduler.get_jobs()
    ])}


@view_config(route_name='resync_all', renderer='json')
def resync_all(request):
    return resync_auctions(request)


@view_config(route_name='resync_back', renderer='json')
def resync_back(request):
    return resync_auctions_back(request)


@view_config(route_name='resync', renderer='json')
def resync(request):
    return resync_auction(request)


@view_config(route_name='recheck', renderer='json')
def recheck(request):
    return recheck_auction(request)


@view_config(route_name='calendar', renderer='json')
def calendar_view(request):
    calendar = get_calendar(request.registry.db)
    return sorted([i for i in calendar if not i.startswith('_')])


@view_config(route_name='calendar_entry', renderer='json')
def calendar_entry_view(request):
    date = request.matchdict['date']
    if request.method == 'GET':
        calendar = get_calendar(request.registry.db)
        return calendar.get(date, False)
    elif request.method == 'POST':
        set_holiday(request.registry.db, date)
        return True
    elif request.method == 'DELETE':
        delete_holiday(request.registry.db, date)
        return False


@view_config(route_name='streams', renderer='json')
def streams_view(request):
    if request.method == 'GET':
        for stream_key in STREAMS_KEYS:
            if request.params.get(stream_key, '') in [
                'True', 'true', 'y', 'yes', 'Yes'
            ]:
                break
        else:
            stream_key = 'streams'
        return get_streams(request.registry.db, stream_key)
    elif request.method == 'POST':
        result = False
        for stream_key in STREAMS_KEYS:
            streams = request.params.get(stream_key, '')
            if streams and streams.isdigit():
                set_streams(request.registry.db, int(streams), stream_key)
                result = True
        return result
    return False
