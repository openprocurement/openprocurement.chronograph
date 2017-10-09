# -*- coding: utf-8 -*-
import grequests
import requests
from couchdb.http import ResourceConflict
from datetime import datetime, timedelta
from gevent.pool import Pool
from iso8601 import parse_date
from json import dumps
from logging import getLogger
from openprocurement.chronograph.utils import context_unpack
from openprocurement.chronograph.design import plan_auctions_view
from openprocurement.chronograph.constants import (
    CALENDAR_ID,
    STREAMS_ID,
    WORKING_DAY_START,
    INSIDER_WORKING_DAY_START,
    WORKING_DAY_END,
    WORKING_DAY_DURATION,
    ROUNDING,
    MIN_PAUSE,
    BIDDER_TIME,
    SERVICE_TIME,
    SMOOTHING_MIN,
    SMOOTHING_REMIN,
    SMOOTHING_MAX,
    NOT_CLASSIC_AUCTIONS,
    DEFAULT_STREAMS_DOC
)
from os import environ
from pytz import timezone
from random import randint
from time import sleep


LOGGER = getLogger(__name__)
TZ = timezone(environ['TZ'] if 'TZ' in environ else 'Europe/Kiev')

ADAPTER = requests.adapters.HTTPAdapter(pool_connections=3, pool_maxsize=3)
SESSION = requests.Session()
SESSION.mount('http://', ADAPTER)
SESSION.mount('https://', ADAPTER)
POOL = Pool(1)


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


def get_streams(db, streams_id=STREAMS_ID, classic_auction=True):
        streams = db.get(streams_id, DEFAULT_STREAMS_DOC)
        if classic_auction:
            return streams.get('streams', DEFAULT_STREAMS_DOC['streams'])
        else:
            return streams.get('dutch_streams',
                               DEFAULT_STREAMS_DOC['dutch_streams'])


def set_streams(db, streams=None, dutch_streams=None, streams_id=STREAMS_ID):
    streams_doc = db.get(streams_id, DEFAULT_STREAMS_DOC)
    if streams is not None:
        streams_doc['streams'] = streams
    if dutch_streams is not None:
        streams_doc['dutch_streams'] = dutch_streams
    db.save(streams_doc)


def get_date(db, mode, date, classic_auction=True):
    plan_id = 'plan{}_{}'.format(mode, date.isoformat())
    plan = db.get(plan_id, {'_id': plan_id})
    if classic_auction:
        plan_date_end = plan.get('time', WORKING_DAY_START.isoformat())
        stream = plan.get('streams', 1)
    else:
        plan_date_end = INSIDER_WORKING_DAY_START.isoformat()
        stream = len(plan.get('dutch_streams', []))
    plan_date = parse_date(date.isoformat() + 'T' + plan_date_end, None)
    plan_date = plan_date.astimezone(TZ) if plan_date.tzinfo else TZ.localize(plan_date)
    return plan_date.time(), stream, plan


def set_date(db, plan, end_time, cur_stream, auction_id, start_time,
             new_slot=True, classic_auction=True):
    if classic_auction:
        if new_slot:
            plan['time'] = end_time.isoformat()
            plan['streams'] = cur_stream
        stream_id = 'stream_{}'.format(cur_stream)
        stream = plan.get(stream_id, {})
        stream[start_time.isoformat()] = auction_id
        plan[stream_id] = stream
    else:
        dutch_streams = plan.get('dutch_streams', [])
        dutch_streams.append(auction_id)
        plan['dutch_streams'] = dutch_streams
    db.save(plan)


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


def planning_auction(auction, start, db, quick=False, lot_id=None):
    tid = auction.get('id', '')
    mode = auction.get('mode', '')
    classic_auction = auction.get('procurementMethodType') not in \
        NOT_CLASSIC_AUCTIONS
    skipped_days = 0
    if quick:
        quick_start = calc_auction_end_time(0, start)
        return (quick_start, 0, skipped_days)
    calendar = get_calendar(db)
    streams = get_streams(db, classic_auction=classic_auction)
    start += timedelta(hours=1)
    if start.time() > WORKING_DAY_START:
        nextDate = start.date() + timedelta(days=1)
    else:
        nextDate = start.date()
    new_slot = True
    while True:
        # skip Saturday and Sunday
        if calendar.get(nextDate.isoformat()) or nextDate.weekday() in [5, 6]:
            nextDate += timedelta(days=1)
            continue
        dayStart, stream, plan = get_date(db, mode, nextDate,
                                          classic_auction=classic_auction)
        if not classic_auction:  # dgfInsider
            if stream < streams:
                start = TZ.localize(datetime.combine(nextDate, dayStart))
                end = start + WORKING_DAY_DURATION
                break
        else:                    # classic_auction
            freeSlot = find_free_slot(plan)
            if freeSlot:
                startDate, stream = freeSlot
                start, end, dayStart, new_slot = startDate, startDate, startDate.time(), False
                break
            if dayStart >= WORKING_DAY_END and stream < streams:
                stream += 1
                dayStart = WORKING_DAY_START

            start = TZ.localize(datetime.combine(nextDate, dayStart))
            end = start + timedelta(minutes=30)
            # end = calc_auction_end_time(auction.get('numberOfBids', len(auction.get('bids', []))), start)
            if dayStart == WORKING_DAY_START and end > TZ.localize(datetime.combine(nextDate, WORKING_DAY_END)) and stream <= streams:
                break
            elif end <= TZ.localize(datetime.combine(nextDate, WORKING_DAY_END)) and stream <= streams:
                break
        nextDate += timedelta(days=1)
        skipped_days += 1
    #for n in range((end.date() - start.date()).days):
        #date = start.date() + timedelta(n)
        #_, dayStream = get_date(db, mode, date.date())
        #set_date(db, mode, date.date(), WORKING_DAY_END, dayStream+1)
    set_date(db, plan, end.time(), stream, "_".join([tid, lot_id]) if lot_id else tid, dayStart, new_slot, classic_auction)
    return (start, stream, skipped_days)


def skipped_days(days):
    days_str = ''
    if days:
        days_str = ' Skipped {} full days.'.format(days)
    return days_str


def check_auction(request, auction, db):
    now = get_now()
    quick = environ.get('SANDBOX_MODE', False) and u'quick' in auction.get('submissionMethodDetails', '')
    if not auction.get('lots') and 'shouldStartAfter' in auction.get('auctionPeriod', {}) and auction['auctionPeriod']['shouldStartAfter'] > auction['auctionPeriod'].get('startDate'):
        period = auction.get('auctionPeriod')
        shouldStartAfter = max(parse_date(period.get('shouldStartAfter'), TZ).astimezone(TZ), now)
        planned = False
        while not planned:
            try:
                auctionPeriod, stream, skip_days = planning_auction(auction, shouldStartAfter, db, quick)
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
                    auctionPeriod, stream, skip_days = planning_auction(auction, shouldStartAfter, db, quick, lot_id)
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


def get_request(url, auth, headers=None):
    tx = ty = 1
    while True:
        try:
            request = grequests.get(url, auth=auth, headers=headers, session=SESSION)
            grequests.send(request, POOL).join()
            r = request.response
        except:
            pass
        else:
            break
        sleep(tx)
        tx, ty = ty, tx + ty
    return r


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


def resync_auction(request):
    auction_id = request.matchdict['auction_id']
    scheduler = request.registry.scheduler
    url = request.registry.api_url + 'auctions/' + auction_id
    api_token = request.registry.api_token
    resync_url = request.registry.callback_url + 'resync/' + auction_id
    recheck_url = request.registry.callback_url + 'recheck/' + auction_id
    db = request.registry.db
    request_id = request.environ.get('REQUEST_ID', '')
    next_check = None
    next_sync = None
    r = get_request(url, auth=(api_token, ''), headers={'X-Client-Request-ID': request_id})
    if r.status_code != requests.codes.ok:
        LOGGER.error("Error {} on getting auction '{}': {}".format(r.status_code, url, r.text),
                     extra=context_unpack(request, {'MESSAGE_ID': 'error_get_auction'}, {'ERROR_STATUS': r.status_code}))
        if r.status_code == requests.codes.not_found:
            return
        changes = None
        next_sync = get_now() + timedelta(seconds=randint(SMOOTHING_REMIN, SMOOTHING_MAX))
    else:
        json = r.json()
        auction = json['data']
        changes = check_auction(request, auction, db)
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
                if r.json()['data'].get('next_check'):
                    next_check = parse_date(r.json()['data']['next_check'], TZ).astimezone(TZ)
    if next_check:
        check_args = dict(timezone=TZ, id="recheck_{}".format(auction_id),
                          name="Recheck {}".format(auction_id),
                          misfire_grace_time=60 * 60, replace_existing=True,
                          args=[recheck_url, None])
        if next_check < get_now():
            scheduler.add_job(push, 'date', run_date=get_now()+timedelta(seconds=randint(SMOOTHING_MIN, SMOOTHING_MAX)), **check_args)
        else:
            scheduler.add_job(push, 'date', run_date=next_check+timedelta(seconds=randint(SMOOTHING_MIN, SMOOTHING_MAX)), **check_args)
    if next_sync:
        scheduler.add_job(push, 'date', run_date=next_sync+timedelta(seconds=randint(SMOOTHING_MIN, SMOOTHING_MAX)), timezone=TZ,
                          id=auction_id, name="Resync {}".format(auction_id),
                          misfire_grace_time=60 * 60, replace_existing=True,
                          args=[resync_url, None])
    return next_sync and next_sync.isoformat()


def recheck_auction(request):
    auction_id = request.matchdict['auction_id']
    scheduler = request.registry.scheduler
    url = request.registry.api_url + 'auctions/' + auction_id
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
    elif r.json() and r.json()['data'].get('next_check'):
        next_check = parse_date(r.json()['data']['next_check'], TZ).astimezone(TZ)
    if next_check:
        check_args = dict(timezone=TZ, id="recheck_{}".format(auction_id),
                          name="Recheck {}".format(auction_id),
                          misfire_grace_time=60 * 60, replace_existing=True,
                          args=[recheck_url, None])
        if next_check < get_now():
            scheduler.add_job(push, 'date', run_date=get_now()+timedelta(seconds=randint(SMOOTHING_MIN, SMOOTHING_MAX)), **check_args)
        else:
            scheduler.add_job(push, 'date', run_date=next_check+timedelta(seconds=randint(SMOOTHING_MIN, SMOOTHING_MAX)), **check_args)
    return next_check and next_check.isoformat()


def free_slot(db, plan_id, plan_time, auction_id, classic_auction=True):
    slot = plan_time.time().isoformat()
    done = False
    while not done:
        try:
            plan = db.get(plan_id)
            if classic_auction:
                streams = plan['streams']
                for cur_stream in range(1, streams + 1):
                    stream_id = 'stream_{}'.format(cur_stream)
                    if plan[stream_id].get(slot) == auction_id:
                        plan[stream_id][slot] = None
            else:
                slots = plan.get('dutch_streams', [])
                pops = []
                for i in xrange(0, len(slots)):
                    if slots[i] == auction_id:
                        pops.append(i)
                pops.sort(reverse=True)
                for p in pops:
                    slots.pop(p)
                plan['dutch_streams'] = slots
            db.save(plan)
            done = True
        except ResourceConflict:
            done = False
        except:
            done = True


def check_inner_auction(db, auction):
    classic_auction = \
        auction.get('procurementMethodType') not in NOT_CLASSIC_AUCTIONS
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
            free_slot(db, plan_doc, plan_time, auction['id'], classic_auction)
        elif key and (not lots.get(key) or lots.get(key) and not
                      plan_time < lots.get(key) < plan_time +
                      timedelta(minutes=30)):
            free_slot(db, plan_doc, plan_time, "_".join([auction['id'], key]),
                      classic_auction)


def process_listing(auctions, scheduler, callback_url, db, check=True):
    run_date = get_now()
    for auction in auctions:
        if check:
            check_inner_auction(db, auction)
        tid = auction['id']
        next_check = auction.get('next_check')
        if next_check:
            check_args = dict(timezone=TZ, id="recheck_{}".format(tid),
                              name="Recheck {}".format(tid),
                              misfire_grace_time=60 * 60, replace_existing=True,
                              args=[callback_url + 'recheck/' + tid, None])
            next_check = parse_date(next_check, TZ).astimezone(TZ)
            recheck_job = scheduler.get_job("recheck_{}".format(tid))
            if next_check < run_date:
                scheduler.add_job(push, 'date', run_date=run_date+timedelta(seconds=randint(SMOOTHING_MIN, SMOOTHING_MAX)), **check_args)
            elif not recheck_job or recheck_job.next_run_time != next_check:
                scheduler.add_job(push, 'date', run_date=next_check+timedelta(seconds=randint(SMOOTHING_MIN, SMOOTHING_MAX)), **check_args)
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
    if not next_url or 'opt_fields=status%2CauctionPeriod%2CprocurementMethodType%2Clots%2Cnext_check' not in next_url:
        next_url = request.registry.api_url + 'auctions?mode=_all_&feed=changes&descending=1&opt_fields=status%2CauctionPeriod%2CprocurementMethodType%2Clots%2Cnext_check'
    scheduler = request.registry.scheduler
    api_token = request.registry.api_token
    callback_url = request.registry.callback_url
    request_id = request.environ.get('REQUEST_ID', '')
    while True:
        try:
            r = get_request(next_url, auth=(api_token, ''), headers={'X-Client-Request-ID': request_id})
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
            process_listing(json['data'], scheduler, callback_url, request.registry.db)
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
    if not next_url:
        next_url = request.registry.api_url + 'auctions?mode=_all_&feed=changes&descending=1&opt_fields=status%2CauctionPeriod%2CprocurementMethodType%2Clots%2Cnext_check'
    scheduler = request.registry.scheduler
    api_token = request.registry.api_token
    callback_url = request.registry.callback_url
    request_id = request.environ.get('REQUEST_ID', '')
    LOGGER.info("Resync back started", extra=context_unpack(request, {'MESSAGE_ID': 'resync_back_started'}))
    while True:
        try:
            r = get_request(next_url, auth=(api_token, ''), headers={'X-Client-Request-ID': request_id})
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
            process_listing(json['data'], scheduler, callback_url, request.registry.db, False)
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
