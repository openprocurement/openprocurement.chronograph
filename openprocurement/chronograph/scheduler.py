# -*- coding: utf-8 -*-
import requests
from couchdb.http import ResourceConflict
from datetime import timedelta
from iso8601 import parse_date
from json import dumps
from logging import getLogger
from openprocurement.chronograph.utils import (
    context_unpack, update_next_check_job, push,
    get_request, calc_auction_end_time, get_calendar,
    skipped_days, randomize, get_now, get_manager_for_auction
)
from openprocurement.chronograph.design import plan_auctions_view
from openprocurement.chronograph.constants import (
    WORKING_DAY_START,
    SMOOTHING_MIN,
    SMOOTHING_REMIN,
    SMOOTHING_MAX,
)
from os import environ
from pytz import timezone
from random import randint
from time import sleep

from urllib import urlencode
from collections import OrderedDict

LOGGER = getLogger(__name__)
TZ = timezone(environ['TZ'] if 'TZ' in environ else 'Europe/Kiev')

ADAPTER = requests.adapters.HTTPAdapter(pool_connections=3, pool_maxsize=3)
SESSION = requests.Session()
SESSION.mount('http://', ADAPTER)
SESSION.mount('https://', ADAPTER)

BASIC_OPT_FIELDS = ['status', 'next_check']
PLANNING_OPT_FIELDS = ['status', 'next_check', 'auctionPeriod', 'procurementMethodType', 'lots', 'auctionParameters']


def planning_auction(auction, mapper, start, db, quick=False, lot_id=None):
    tid = auction.get('id', '')
    mode = auction.get('mode', '')
    manager = get_manager_for_auction(auction, mapper)
    skipped_days = 0
    if quick:
        quick_start = calc_auction_end_time(0, start)
        return quick_start, 0, skipped_days
    calendar = get_calendar(db)
    streams = manager.get_streams(db)
    start += timedelta(hours=1)
    if start.time() > manager.working_day_start:
        nextDate = start.date() + timedelta(days=1)
    else:
        nextDate = start.date()
    while True:
        # skip Saturday and Sunday
        if calendar.get(nextDate.isoformat()) or nextDate.weekday() in [5, 6]:
            nextDate += timedelta(days=1)
            continue
        dayStart, stream, plan = manager.get_date(db, mode, nextDate)
        result = manager.set_end_of_auction(stream, streams, nextDate, dayStart, plan)
        if result:
            start, end, dayStart, stream, new_slot = result
            break
        nextDate += timedelta(days=1)
        skipped_days += 1
    manager.set_date(db, plan, "_".join([tid, lot_id]) if lot_id else tid, end.time(), stream, dayStart, new_slot)
    return start, stream, skipped_days


def check_auction(request, auction, db, mapper):
    now = get_now()
    quick = environ.get('SANDBOX_MODE', False) and u'quick' in auction.get('submissionMethodDetails', '')
    if not auction.get('lots') and 'shouldStartAfter' in auction.get('auctionPeriod', {}) and auction['auctionPeriod']['shouldStartAfter'] > auction['auctionPeriod'].get('startDate'):
        period = auction.get('auctionPeriod')
        shouldStartAfter = max(parse_date(period.get('shouldStartAfter'), TZ).astimezone(TZ), now)
        planned = False
        while not planned:
            try:
                auctionPeriod, stream, skip_days = planning_auction(auction, mapper, shouldStartAfter, db, quick)
                planned = True
            except ResourceConflict:
                planned = False
        auctionPeriod = randomize(auctionPeriod).isoformat()
        planned = 'replanned' if period.get('startDate') else 'planned'
        LOGGER.info('{} auction for auction {} to {}. Stream {}.{}'.format(planned.title(), auction['id'], auctionPeriod, stream, skipped_days(skip_days)),
                    extra=context_unpack(request,
                                         {'MESSAGE_ID': '{}_auction_auction'.format(planned)},
                                         {'PLANNED_DATE': auctionPeriod, 'PLANNED_STREAM': stream, 'PLANNED_DAYS_SKIPPED': skip_days}))
        return {'auctionPeriod': {'startDate': auctionPeriod}}
    elif auction.get('lots'):
        lots = []
        for lot in auction.get('lots', []):
            if lot['status'] != 'active' or 'shouldStartAfter' not in lot.get('auctionPeriod', {}) or lot['auctionPeriod']['shouldStartAfter'] < lot['auctionPeriod'].get('startDate'):
                lots.append({})
                continue
            period = lot.get('auctionPeriod')
            shouldStartAfter = max(parse_date(period.get('shouldStartAfter'), TZ).astimezone(TZ), now)
            lot_id = lot['id']
            planned = False
            while not planned:
                try:
                    auctionPeriod, stream, skip_days = planning_auction(auction, mapper, shouldStartAfter, db, quick, lot_id)
                    planned = True
                except ResourceConflict:
                    planned = False
            auctionPeriod = randomize(auctionPeriod).isoformat()
            planned = 'replanned' if period.get('startDate') else 'planned'
            lots.append({'auctionPeriod': {'startDate': auctionPeriod}})
            LOGGER.info('{} auction for lot {} of auction {} to {}. Stream {}.{}'.format(planned.title(), lot_id, auction['id'], auctionPeriod, stream, skipped_days(skip_days)),
                        extra=context_unpack(request,
                                             {'MESSAGE_ID': '{}_auction_lot'.format(planned)},
                                             {'PLANNED_DATE': auctionPeriod, 'PLANNED_STREAM': stream, 'PLANNED_DAYS_SKIPPED': skip_days, 'LOT_ID': lot_id}))
        if any(lots):
            return {'lots': lots}
    return None


def resync_auction(request):
    auction_id = request.matchdict['auction_id']
    scheduler = request.registry.scheduler
    url = '{}/{}'.format(request.registry.full_url, auction_id)
    api_token = request.registry.api_token
    resync_url = request.registry.callback_url + 'resync/' + auction_id
    recheck_url = request.registry.callback_url + 'recheck/' + auction_id
    db = request.registry.db
    request_id = request.environ.get('REQUEST_ID', '')
    next_check = None
    next_sync = None
    r = get_request(
        url, auth=(api_token, ''), session=SESSION, headers={'X-Client-Request-ID': request_id}
    )
    if r.status_code != requests.codes.ok:
        LOGGER.error("Error {} on getting auction '{}': {}".format(r.status_code, url, r.text),
                     extra=context_unpack(request, {'MESSAGE_ID': 'error_get_auction'}, {'ERROR_STATUS': r.status_code}))
        if r.status_code == requests.codes.not_found:
            return
        next_sync = get_now() + timedelta(seconds=randint(SMOOTHING_REMIN, SMOOTHING_MAX))
    else:
        json = r.json()
        auction = json['data']
        changes = check_auction(request, auction, db, request.registry.manager_mapper)
        if changes:
            data = dumps({'data': changes})
            r = SESSION.patch(url,
                              data=data,
                              headers={'Content-Type': 'application/json', 'X-Client-Request-ID': request_id},
                              auth=(api_token, ''))
            if r.status_code != requests.codes.ok:
                LOGGER.error("Error {} on updating auction '{}' with '{}': {}".format(r.status_code, url, data, r.text),
                             extra=context_unpack(request, {'MESSAGE_ID': 'error_patch_auction'}, {'ERROR_STATUS': r.status_code}))
                next_sync = get_now() + timedelta(seconds=randint(SMOOTHING_REMIN, SMOOTHING_MAX))
            elif r.json():
                next_check = r.json()['data'].get('next_check')
    if next_check:
        update_next_check_job(next_check, scheduler, auction_id, get_now(), recheck_url)
    if next_sync:
        scheduler.add_job(push, 'date', run_date=next_sync+timedelta(seconds=randint(SMOOTHING_MIN, SMOOTHING_MAX)), timezone=TZ,
                          id=auction_id, name="Resync {}".format(auction_id),
                          misfire_grace_time=60 * 60, replace_existing=True,
                          args=[resync_url, None])
    return next_sync and next_sync.isoformat()


def recheck_auction(request):
    auction_id = request.matchdict['auction_id']
    scheduler = request.registry.scheduler
    url = '{}/{}'.format(request.registry.full_url, auction_id)
    api_token = request.registry.api_token
    recheck_url = request.registry.callback_url + 'recheck/' + auction_id
    request_id = request.environ.get('REQUEST_ID', '')
    next_check = None
    r = SESSION.patch(url,
                      data=dumps({'data': {'id': auction_id}}),
                      headers={'Content-Type': 'application/json', 'X-Client-Request-ID': request_id},
                      auth=(api_token, ''))
    if r.status_code != requests.codes.ok:
        LOGGER.error("Error {} on checking auction '{}': {}".format(r.status_code, url, r.text),
                     extra=context_unpack(request, {'MESSAGE_ID': 'error_check_auction'}, {'ERROR_STATUS': r.status_code}))
        if r.status_code not in [requests.codes.forbidden, requests.codes.not_found]:
            next_check = get_now() + timedelta(minutes=1)
    elif r.json():
        next_check = r.json()['data'].get('next_check')
    if next_check:
        next_check = update_next_check_job(next_check, scheduler, auction_id, get_now(), recheck_url)
    return next_check and next_check.isoformat()


def check_inner_auction(db, auction, mapper):
    manager = get_manager_for_auction(auction, mapper)

    auction_time = auction.get('auctionPeriod', {}).get('startDate') and \
        parse_date(auction.get('auctionPeriod', {}).get('startDate'))
    lots = dict([
        (i['id'], parse_date(i.get('auctionPeriod', {}).get('startDate')))
        for i in auction.get('lots', [])
        if i.get('auctionPeriod', {}).get('startDate')
    ])
    auc_list = [
        (x.key[1], TZ.localize(parse_date(x.value, None)), x.id)
        for x in plan_auctions_view(db, startkey=[auction['id'], None],
                                    endkey=[auction['id'], 32 * "f"])
    ]
    for key, plan_time, plan_doc in auc_list:
        if not key and (not auction_time or not
                        plan_time < auction_time < plan_time +
                        timedelta(minutes=30)):
            manager.free_slot(db, plan_doc, auction['id'], plan_time)
        elif key and (not lots.get(key) or lots.get(key) and not
                      plan_time < lots.get(key) < plan_time +
                      timedelta(minutes=30)):
            manager.free_slot(db, plan_doc, "_".join([auction['id'], key]), plan_time)


def process_listing(auctions, scheduler, callback_url, db, mapper, check=True, planning=True):
    run_date = get_now()
    for auction in auctions:
        if check:
            check_inner_auction(db, auction, mapper)
        tid = auction['id']
        next_check = auction.get('next_check')
        if next_check:
            recheck_url = ''.join([callback_url, 'recheck/', tid])
            update_next_check_job(next_check, scheduler, tid, run_date, recheck_url, True)
        if planning:
            if any([
                'shouldStartAfter' in i.get('auctionPeriod', {}) and i['auctionPeriod']['shouldStartAfter'] > i['auctionPeriod'].get('startDate')
                for i in auction.get('lots', [])
            ]) or (
                'shouldStartAfter' in auction.get('auctionPeriod', {}) and auction['auctionPeriod']['shouldStartAfter'] > auction['auctionPeriod'].get('startDate')
            ):
                resync_job = scheduler.get_job(tid)
                if not resync_job or resync_job.next_run_time > run_date + timedelta(minutes=1):
                    scheduler.add_job(push, 'date', run_date=run_date+timedelta(seconds=randint(SMOOTHING_MIN, SMOOTHING_MAX)), timezone=TZ,
                                      id=tid, name="Resync {}".format(tid),
                                      misfire_grace_time=60 * 60,
                                      args=[callback_url + 'resync/' + tid, None],
                                      replace_existing=True)


def resync_auctions(request):
    next_url = request.params.get('url', '')
    opt_fields = ",".join(BASIC_OPT_FIELDS) if not request.registry.planning else ",".join(PLANNING_OPT_FIELDS)
    if not next_url or urlencode({"opt_fields": opt_fields}) not in next_url:
        query = urlencode(OrderedDict(mode='_all_', feed='changes', descending=1, opt_fields=opt_fields))
        next_url = '{}?{}'.format(request.registry.full_url, query)
    scheduler = request.registry.scheduler
    api_token = request.registry.api_token
    callback_url = request.registry.callback_url
    request_id = request.environ.get('REQUEST_ID', '')
    while True:
        try:
            r = get_request(next_url, auth=(api_token, ''), session=SESSION, headers={'X-Client-Request-ID': request_id})
            if r.status_code == requests.codes.not_found:
                next_url = ''
                break
            elif r.status_code != requests.codes.ok:
                break
            else:
                json = r.json()
                next_url = json['next_page']['uri']
                if "descending=1" in next_url:
                    run_date = get_now()
                    scheduler.add_job(push, 'date', run_date=run_date, timezone=TZ,
                                      id='resync_back', name="Resync back", misfire_grace_time=60 * 60,
                                      args=[callback_url + 'resync_back', {'url': next_url}],
                                      replace_existing=True)
                    next_url = json['prev_page']['uri']
            if not json['data']:
                break
            process_listing(json['data'], scheduler, callback_url, request.registry.db,
                            request.registry.manager_mapper, planning=request.registry.planning)
            sleep(0.1)
        except Exception as e:
            LOGGER.error("Error on resync all: {}".format(repr(e)), extra=context_unpack(request, {'MESSAGE_ID': 'error_resync_all'}))
            break
    run_date = get_now() + timedelta(minutes=1)
    scheduler.add_job(push, 'date', run_date=run_date, timezone=TZ,
                      id='resync_all', name="Resync all",
                      misfire_grace_time=60 * 60,
                      args=[callback_url + 'resync_all', {'url': next_url}],
                      replace_existing=True)
    return next_url


def resync_auctions_back(request):
    next_url = request.params.get('url', '')
    opt_fields = ",".join(BASIC_OPT_FIELDS) if not request.registry.planning else ",".join(PLANNING_OPT_FIELDS)
    if not next_url:
        query = urlencode(OrderedDict(mode='_all_', feed='changes', descending=1, opt_fields=opt_fields))
        next_url = '{}?{}'.format(request.registry.full_url, query)
    scheduler = request.registry.scheduler
    api_token = request.registry.api_token
    callback_url = request.registry.callback_url
    request_id = request.environ.get('REQUEST_ID', '')
    LOGGER.info("Resync back started", extra=context_unpack(request, {'MESSAGE_ID': 'resync_back_started'}))
    while True:
        try:
            r = get_request(next_url, auth=(api_token, ''), session=SESSION, headers={'X-Client-Request-ID': request_id})
            if r.status_code == requests.codes.not_found:
                next_url = ''
                break
            elif r.status_code != requests.codes.ok:
                break
            json = r.json()
            next_url = json['next_page']['uri']
            if not json['data']:
                LOGGER.info("Resync back stopped", extra=context_unpack(request, {'MESSAGE_ID': 'resync_back_stoped'}))
                return next_url
            process_listing(json['data'], scheduler, callback_url, request.registry.db,
                            request.registry.manager_mapper, False, request.registry.planning)
            sleep(0.1)
        except Exception as e:
            LOGGER.error("Error on resync back: {}".format(repr(e)), extra=context_unpack(request, {'MESSAGE_ID': 'error_resync_back'}))
            break
    LOGGER.info("Resync back break", extra=context_unpack(request, {'MESSAGE_ID': 'resync_back_break'}))
    run_date = get_now() + timedelta(minutes=1)
    scheduler.add_job(push, 'date', run_date=run_date, timezone=TZ,
                      id='resync_back', name="Resync back", misfire_grace_time=60 * 60,
                      args=[callback_url + 'resync_back', {'url': next_url}],
                      replace_existing=True)
    return next_url
