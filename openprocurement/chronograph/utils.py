import os
from copy import deepcopy
from datetime import datetime, timedelta
from random import randint
from time import sleep

import grequests
import requests
from gevent.pool import Pool
from iso8601 import parse_date
from pytz import timezone


from openprocurement.chronograph.constants import (
    CALENDAR_ID,
    STREAMS_ID,
    WORKING_DAY_START,
    ROUNDING,
    MIN_PAUSE,
    BIDDER_TIME,
    SERVICE_TIME,
    SMOOTHING_MIN,
    SMOOTHING_MAX,
    DEFAULT_STREAMS_DOC
)

POOL = Pool(1)
TZ = timezone(os.environ['TZ'] if 'TZ' in os.environ else 'Europe/Kiev')


def add_logging_context(event):
    request = event.request
    params = {
        'AUCTIONS_API_URL': request.registry.api_url,
        'TAGS': 'python,chronograph',
        'CURRENT_URL': request.url,
        'CURRENT_PATH': request.path_info,
        'REMOTE_ADDR': request.remote_addr or '',
        'USER_AGENT': request.user_agent or '',
        'AUCTION_ID': '',
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


def get_full_url(registry):
    return '{}{}'.format(registry.api_url, registry.api_resource)


def skipped_days(days):
    days_str = ''
    if days:
        days_str = ' Skipped {} full days.'.format(days)
    return days_str


def get_now():
    return TZ.localize(datetime.now())


def randomize(dt):
    return dt + timedelta(seconds=randint(0, 1799))


def get_calendar(db, calendar_id=CALENDAR_ID):
    return db.get(calendar_id, {'_id': calendar_id})


def set_holiday(db, day):
    calendar = get_calendar(db)
    key = parse_date(day).date().isoformat()
    calendar[key] = True
    db.save(calendar)


def delete_holiday(db, day):
    calendar = get_calendar(db)
    key = parse_date(day).date().isoformat()
    if key in calendar:
        calendar.pop(key)
        db.save(calendar)


def get_streams(db, stream_key='streams', streams_id=STREAMS_ID):
    """
    Backward compatibility version of managers.BaseAuctionsManager method,
    which is left due to views.streams_view dependency
    """
    streams = db.get(streams_id, deepcopy(DEFAULT_STREAMS_DOC))
    return streams.get(stream_key, DEFAULT_STREAMS_DOC[stream_key])


def set_streams(db, streams=None, stream_key=None, streams_id=STREAMS_ID):
    streams_doc = db.get(streams_id, deepcopy(DEFAULT_STREAMS_DOC))
    if streams is not None and stream_key is not None:
        streams_doc[stream_key] = streams
    db.save(streams_doc)


def calc_auction_end_time(bids, start):
    end = start + bids * BIDDER_TIME + SERVICE_TIME + MIN_PAUSE
    seconds = (end - TZ.localize(datetime.combine(end, WORKING_DAY_START))).seconds
    roundTo = ROUNDING.seconds
    rounding = (seconds + roundTo - 1) // roundTo * roundTo
    return (end + timedelta(0, rounding - seconds, -end.microsecond)).astimezone(TZ)


def find_free_slot(plan):
    streams = plan.get('streams', 0)
    for cur_stream in range(1, streams + 1):
        stream_id = 'stream_{}'.format(cur_stream)
        for slot in plan[stream_id]:
            if plan[stream_id].get(slot) is None:
                plan_date = parse_date(plan['_id'].split('_')[1] + 'T' + slot, None)
                plan_date = plan_date.astimezone(TZ) if plan_date.tzinfo else TZ.localize(plan_date)
                return plan_date, cur_stream


def update_next_check_job(next_check, scheduler, auction_id,
                          run_date, recheck_url, check_next_run_time=False):
    next_check = parse_date(next_check, TZ).astimezone(TZ)
    check_args = dict(timezone=TZ, id="recheck_{}".format(auction_id),
                      name="Recheck {}".format(auction_id),
                      misfire_grace_time=60 * 60, replace_existing=True,
                      args=[recheck_url, None])
    if next_check < run_date:
        scheduler.add_job(push, 'date', run_date=run_date + timedelta(seconds=randint(SMOOTHING_MIN, SMOOTHING_MAX)),
                          **check_args)
    elif check_next_run_time:
        recheck_job = scheduler.get_job("recheck_{}".format(auction_id))
        if not recheck_job or recheck_job.next_run_time != next_check:
            scheduler.add_job(push, 'date',
                              run_date=next_check + timedelta(seconds=randint(SMOOTHING_MIN, SMOOTHING_MAX)),
                              **check_args)
    else:
        scheduler.add_job(push, 'date', run_date=next_check + timedelta(seconds=randint(SMOOTHING_MIN, SMOOTHING_MAX)),
                          **check_args)
    return next_check


def push(url, params):
    tx = ty = 1
    while True:
        try:
            r = requests.get(url, params=params)
        except:
            pass
        else:
            if r.status_code == requests.codes.ok:
                break
        sleep(tx)
        tx, ty = ty, tx + ty


def get_request(url, auth, session, headers=None):
    tx = ty = 1
    while True:
        try:
            request = grequests.get(url, auth=auth, headers=headers, session=session)
            grequests.send(request, POOL).join()
            r = request.response
        except:
            pass
        else:
            break
        sleep(tx)
        tx, ty = ty, tx + ty
    return r


def get_manager_for_auction(auction, mapper):
    default_manager = mapper['types'].get('english', None)

    auction_type = auction.get('auctionParameters', {}).get('type', None)
    if auction_type:
        return mapper['types'].get(auction_type, default_manager)
    else:
        pmt = auction.get('procurementMethodType')
        return mapper['pmts'].get(pmt, default_manager)
