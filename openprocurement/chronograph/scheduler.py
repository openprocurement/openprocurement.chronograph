# -*- coding: utf-8 -*-
import grequests
import requests
from couchdb.http import ResourceConflict
from datetime import datetime, timedelta, time
from gevent.pool import Pool
from iso8601 import parse_date
from json import dumps
from logging import getLogger
from openprocurement.chronograph.utils import context_unpack
from os import environ
from pytz import timezone
from random import randint
from time import sleep


LOGGER = getLogger(__name__)
TZ = timezone(environ['TZ'] if 'TZ' in environ else 'Europe/Kiev')
CALENDAR_ID = 'calendar'
STREAMS_ID = 'streams'
WORKING_DAY_START = time(11, 0)
WORKING_DAY_END = time(16, 0)
ROUNDING = timedelta(minutes=15)
MIN_PAUSE = timedelta(minutes=3)
BIDDER_TIME = timedelta(minutes=6)
SERVICE_TIME = timedelta(minutes=9)
STAND_STILL_TIME = timedelta(days=1)
SESSION = requests.Session()
POOL = Pool(1)


def get_now():
    return TZ.localize(datetime.now())


def randomize(dt):
    return dt + timedelta(seconds=randint(0, 900))


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


def get_streams(db, streams_id=STREAMS_ID):
    return db.get(streams_id, {'_id': streams_id, 'streams': 10}).get('streams')


def set_streams(db, streams, streams_id=STREAMS_ID):
    streams_doc = db.get(streams_id, {'_id': streams_id})
    streams_doc['streams'] = streams
    db.save(streams_doc)


def get_date(db, mode, date):
    plan_id = 'plan{}_{}'.format(mode, date.isoformat())
    plan = db.get(plan_id, {'_id': plan_id})
    plan_date_end = plan.get('time', WORKING_DAY_START.isoformat())
    plan_date = parse_date(date.isoformat() + 'T' + plan_date_end, None)
    plan_date = plan_date.astimezone(TZ) if plan_date.tzinfo else TZ.localize(plan_date)
    return plan_date.time(), plan.get('streams', 1), plan


def set_date(db, plan, end_time, cur_stream, tender_id, start_time):
    plan['time'] = end_time.isoformat()
    plan['streams'] = cur_stream
    stream_id = 'stream_{}'.format(cur_stream)
    stream = plan.get(stream_id, {})
    stream[start_time.isoformat()] = tender_id
    plan[stream_id] = stream
    db.save(plan)


def calc_auction_end_time(bids, start):
    end = start + bids * BIDDER_TIME + SERVICE_TIME + MIN_PAUSE
    seconds = (end - TZ.localize(datetime.combine(end, WORKING_DAY_START))).seconds
    roundTo = ROUNDING.seconds
    rounding = (seconds + roundTo - 1) // roundTo * roundTo
    return (end + timedelta(0, rounding - seconds, -end.microsecond)).astimezone(TZ)


def planning_auction(tender, start, db, quick=False, lot_id=None):
    tid = tender.get('id', '')
    mode = tender.get('mode', '')
    calendar = get_calendar(db)
    streams = get_streams(db)
    skipped_days = 0
    if quick:
        quick_start = calc_auction_end_time(0, start)
        return (quick_start, 0, skipped_days)
    start += timedelta(hours=1)
    if start.time() < WORKING_DAY_START:
        nextDate = start.date()
    else:
        nextDate = start.date() + timedelta(days=1)
    while True:
        if calendar.get(nextDate.isoformat()) or nextDate.weekday() in [5, 6]:  # skip Saturday and Sunday
            nextDate += timedelta(days=1)
            continue
        dayStart, stream, plan = get_date(db, mode, nextDate)
        if dayStart >= WORKING_DAY_END and stream >= streams:
            nextDate += timedelta(days=1)
            skipped_days += 1
            continue
        if dayStart >= WORKING_DAY_END and stream < streams:
            stream += 1
            dayStart = WORKING_DAY_START
        start = TZ.localize(datetime.combine(nextDate, dayStart))
        # end = calc_auction_end_time(tender.get('numberOfBids', len(tender.get('bids', []))), start)
        end = start + timedelta(minutes=30)
        if dayStart == WORKING_DAY_START and end > TZ.localize(datetime.combine(nextDate, WORKING_DAY_END)):
            break
        elif end <= TZ.localize(datetime.combine(nextDate, WORKING_DAY_END)):
            break
        nextDate += timedelta(days=1)
        skipped_days += 1
    #for n in range((end.date() - start.date()).days):
        #date = start.date() + timedelta(n)
        #_, dayStream = get_date(db, mode, date.date())
        #set_date(db, mode, date.date(), WORKING_DAY_END, dayStream+1)
    set_date(db, plan, end.time(), stream, "_".join([tid, lot_id]) if lot_id else tid, dayStart)
    return (start, stream, skipped_days)


def skipped_days(days):
    days_str = ''
    if days:
        days_str = ' Skipped {} full days.'.format(days)
    return days_str


def check_tender(request, tender, db):
    tenderPeriodEnd = tender.get('tenderPeriod', {}).get('endDate')
    tenderPeriodEnd = tenderPeriodEnd and parse_date(tenderPeriodEnd, TZ).astimezone(TZ)
    now = get_now()
    if not tender.get('lots') and tender['status'] in ['active.tendering', 'active.auction'] and not tender.get('auctionPeriod'):
        planned = False
        quick = environ.get('SANDBOX_MODE', False) and u'quick' in tender.get('submissionMethodDetails', '')
        while not planned:
            try:
                auctionPeriod, stream, skip_days = planning_auction(tender, tenderPeriodEnd, db, quick)
                planned = True
            except ResourceConflict:
                planned = False
        auctionPeriod = randomize(auctionPeriod)
        tenderAuctionEnd = calc_auction_end_time(tender.get('numberOfBids', len(tender.get('bids', []))), auctionPeriod)
        auctionPeriod = auctionPeriod.isoformat()
        LOGGER.info('Planned auction for tender {} to {}. Stream {}.{}'.format(tender['id'], auctionPeriod, stream, skipped_days(skip_days)),
                    extra=context_unpack(request,
                                         {'MESSAGE_ID': 'planned_auction_tender'},
                                         {'PLANNED_DATE': auctionPeriod, 'PLANNED_STREAM': stream, 'PLANNED_DAYS_SKIPPED': skip_days}))
        return {'auctionPeriod': {'startDate': auctionPeriod}}, randomize(tenderPeriodEnd) if tender['status'] == 'active.tendering' else tenderAuctionEnd + MIN_PAUSE
    elif not tender.get('lots') and tender['status'] == 'active.auction' and tender.get('auctionPeriod'):
        tenderAuctionStart = parse_date(tender.get('auctionPeriod', {}).get('startDate'), TZ).astimezone(TZ)
        tenderAuctionEnd = calc_auction_end_time(tender.get('numberOfBids', len(tender.get('bids', []))), tenderAuctionStart)
        if now > tenderAuctionEnd + MIN_PAUSE:
            planned = False
            quick = environ.get('SANDBOX_MODE', False) and u'quick' in tender.get('submissionMethodDetails', '')
            while not planned:
                try:
                    auctionPeriod, stream, skip_days = planning_auction(tender, now, db, quick)
                    planned = True
                except ResourceConflict:
                    planned = False
            auctionPeriod = randomize(auctionPeriod)
            tenderAuctionEnd = calc_auction_end_time(tender.get('numberOfBids', len(tender.get('bids', []))), auctionPeriod)
            auctionPeriod = auctionPeriod.isoformat()
            LOGGER.info('Replanned auction for tender {} to {}. Stream {}.{}'.format(tender['id'], auctionPeriod, stream, skipped_days(skip_days)),
                        extra=context_unpack(request,
                                             {'MESSAGE_ID': 'replanned_auction_tender'},
                                             {'PLANNED_DATE': auctionPeriod, 'PLANNED_STREAM': stream, 'PLANNED_DAYS_SKIPPED': skip_days}))
            return {'auctionPeriod': {'startDate': auctionPeriod}}, tenderAuctionEnd + MIN_PAUSE
        else:
            return None, tenderAuctionEnd + MIN_PAUSE
    elif tender.get('lots') and tender['status'] in ['active.tendering', 'active.auction'] and any([not lot.get('auctionPeriod') for lot in tender['lots'] if lot['status'] == 'active']):
        quick = environ.get('SANDBOX_MODE', False) and u'quick' in tender.get('submissionMethodDetails', '')
        lots = []
        for lot in tender.get('lots', []):
            if lot['status'] != 'active' or lot.get('auctionPeriod'):
                lots.append({})
                continue
            lot_id = lot['id']
            planned = False
            while not planned:
                try:
                    auctionPeriod, stream, skip_days = planning_auction(tender, tenderPeriodEnd, db, quick, lot_id)
                    planned = True
                except ResourceConflict:
                    planned = False
            auctionPeriod = randomize(auctionPeriod).isoformat()
            lots.append({'auctionPeriod': {'startDate': auctionPeriod}})
            LOGGER.info('Planned auction for lot {} of tender {} to {}. Stream {}.{}'.format(lot_id, tender['id'], auctionPeriod, stream, skipped_days(skip_days)),
                        extra=context_unpack(request,
                                             {'MESSAGE_ID': 'planned_auction_lot'},
                                             {'PLANNED_DATE': auctionPeriod, 'PLANNED_STREAM': stream, 'PLANNED_DAYS_SKIPPED': skip_days, 'LOT_ID': lot_id}))
        return {'lots': lots}, randomize(tenderPeriodEnd) if tender['status'] == 'active.tendering' else now
    elif tender.get('lots') and tender['status'] == 'active.auction':
        quick = environ.get('SANDBOX_MODE', False) and u'quick' in tender.get('submissionMethodDetails', '')
        lots = []
        lots_ends = []
        for lot in tender.get('lots', []):
            if lot['status'] != 'active' or lot.get('auctionPeriod', {}).get('endDate'):
                lots.append({})
                continue
            lot_id = lot['id']
            lotAuctionStart = parse_date(lot.get('auctionPeriod', {}).get('startDate'), TZ).astimezone(TZ)
            lotAuctionEnd = calc_auction_end_time(lot['numberOfBids'], lotAuctionStart)
            if now > lotAuctionEnd + MIN_PAUSE:
                planned = False
                while not planned:
                    try:
                        auctionPeriod, stream, skip_days = planning_auction(tender, now, db, quick, lot_id)
                        planned = True
                    except ResourceConflict:
                        planned = False
                auctionPeriod = randomize(auctionPeriod)
                lotAuctionEnd = calc_auction_end_time(lot['numberOfBids'], auctionPeriod)
                auctionPeriod = auctionPeriod.isoformat()
                lots.append({'auctionPeriod': {'startDate': auctionPeriod}})
                lots_ends.append(lotAuctionEnd + MIN_PAUSE)
                LOGGER.info('Replanned auction for lot {} of tender {} to {}. Stream {}.{}'.format(lot_id, tender['id'], auctionPeriod, stream, skipped_days(skip_days)),
                            extra=context_unpack(request,
                                                 {'MESSAGE_ID': 'replanned_auction_lot'},
                                                 {'PLANNED_DATE': auctionPeriod, 'PLANNED_STREAM': stream, 'PLANNED_DAYS_SKIPPED': skip_days, 'LOT_ID': lot_id}))
            else:
                lots_ends.append(lotAuctionEnd + MIN_PAUSE)
        if any(lots):
            return {'lots': lots}, min(lots_ends)
        else:
            return None, min(lots_ends)
    return None, None


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


def resync_tender(request):
    tender_id = request.matchdict['tender_id']
    scheduler = request.registry.scheduler
    url = request.registry.api_url + 'tenders/' + tender_id
    api_token = request.registry.api_token
    resync_url = request.registry.callback_url + 'resync/' + tender_id
    recheck_url = request.registry.callback_url + 'recheck/' + tender_id
    db = request.registry.db
    request_id = request.environ.get('REQUEST_ID', '')
    next_check = None
    next_sync = None
    r = get_request(url, auth=(api_token, ''), headers={'X-Client-Request-ID': request_id})
    if r.status_code != requests.codes.ok:
        LOGGER.error("Error {} on getting tender '{}': {}".format(r.status_code, url, r.text),
                     extra=context_unpack(request, {'MESSAGE_ID': 'error_get_tender'}, {'ERROR_STATUS': r.status_code}))
        if r.status_code == requests.codes.not_found:
            return
        changes = None
        next_sync = get_now() + timedelta(minutes=1)
    else:
        json = r.json()
        tender = json['data']
        changes, next_sync = check_tender(request, tender, db)
        if changes:
            data = dumps({'data': changes})
            r = SESSION.patch(url,
                              data=data,
                              headers={'Content-Type': 'application/json', 'X-Client-Request-ID': request_id},
                              auth=(api_token, ''))
            if r.status_code != requests.codes.ok:
                LOGGER.error("Error {} on updating tender '{}' with '{}': {}".format(r.status_code, url, data, r.text),
                             extra=context_unpack(request, {'MESSAGE_ID': 'error_patch_tender'}, {'ERROR_STATUS': r.status_code}))
                next_sync = get_now() + timedelta(minutes=1)
            elif r.json():
                if not r.json()['data']['status'].startswith('active'):
                    next_sync = None
                if r.json()['data']['next_check']:
                    next_check = parse_date(r.json()['data']['next_check'], TZ).astimezone(TZ)
    if next_check:
        check_args = dict(timezone=TZ, id="recheck_{}".format(tender_id),
                          name="Recheck {}".format(tender_id),
                          misfire_grace_time=60 * 60, replace_existing=True,
                          args=[recheck_url, None])
        if next_check < get_now():
            scheduler.add_job(push, 'date', run_date=get_now(), **check_args)
        else:
            scheduler.add_job(push, 'date', run_date=next_check, **check_args)
    if next_sync:
        scheduler.add_job(push, 'date', run_date=next_sync, timezone=TZ,
                          id=tender_id, name="Resync {}".format(tender_id),
                          misfire_grace_time=60 * 60, replace_existing=True,
                          args=[resync_url, None])
    return next_sync and next_sync.isoformat()


def recheck_tender(request):
    tender_id = request.matchdict['tender_id']
    scheduler = request.registry.scheduler
    url = request.registry.api_url + 'tenders/' + tender_id
    api_token = request.registry.api_token
    recheck_url = request.registry.callback_url + 'recheck/' + tender_id
    request_id = request.environ.get('REQUEST_ID', '')
    next_check = None
    r = SESSION.patch(url,
                      data=dumps({'data': {'id': tender_id}}),
                      headers={'Content-Type': 'application/json', 'X-Client-Request-ID': request_id},
                      auth=(api_token, ''))
    if r.status_code != requests.codes.ok:
        LOGGER.error("Error {} on checking tender '{}': {}".format(r.status_code, url, r.text),
                     extra=context_unpack(request, {'MESSAGE_ID': 'error_check_tender'}, {'ERROR_STATUS': r.status_code}))
        if r.status_code not in [requests.codes.forbidden, requests.codes.not_found]:
            next_check = get_now() + timedelta(minutes=1)
    elif r.json() and r.json()['data']['next_check']:
        next_check = parse_date(r.json()['data']['next_check'], TZ).astimezone(TZ)
    if next_check:
        check_args = dict(timezone=TZ, id="recheck_{}".format(tender_id),
                          name="Recheck {}".format(tender_id),
                          misfire_grace_time=60 * 60, replace_existing=True,
                          args=[recheck_url, None])
        if next_check < get_now():
            scheduler.add_job(push, 'date', run_date=get_now(), **check_args)
        else:
            scheduler.add_job(push, 'date', run_date=next_check, **check_args)
    return next_check and next_check.isoformat()


def process_listing(tenders, scheduler, callback_url):
    run_date = get_now()
    for tender in tenders:
        tid = tender['id']
        next_check = tender.get('next_check')
        if next_check:
            check_args = dict(timezone=TZ, id="recheck_{}".format(tid),
                              name="Recheck {}".format(tid),
                              misfire_grace_time=60 * 60, replace_existing=True,
                              args=[callback_url + 'recheck/' + tid, None])
            next_check = parse_date(next_check, TZ).astimezone(TZ)
            recheck_job = scheduler.get_job("recheck_{}".format(tid))
            if next_check < run_date:
                scheduler.add_job(push, 'date', run_date=run_date, **check_args)
            elif not recheck_job or recheck_job.next_run_time != next_check:
                scheduler.add_job(push, 'date', run_date=next_check, **check_args)
        tender_status = tender.get('status', 'active')
        resync_job = scheduler.get_job(tid)
        if tender_status in ['active.tendering', 'active.auction'] and 'auctionPeriod' not in tender and (not resync_job or resync_job.next_run_time > run_date + timedelta(minutes=1)):
            scheduler.add_job(push, 'date', run_date=run_date, timezone=TZ,
                              id=tid, name="Resync {}".format(tid), misfire_grace_time=60 * 60,
                              args=[callback_url + 'resync/' + tid, None],
                              replace_existing=True)
        elif tender_status == 'active.auction' and not resync_job:
            scheduler.add_job(push, 'date', run_date=run_date, timezone=TZ,
                              id=tid, name="Resync {}".format(tid), misfire_grace_time=60 * 60,
                              args=[callback_url + 'resync/' + tid, None],
                              replace_existing=True)


def resync_tenders(request):
    next_url = request.params.get('url', '')
    if not next_url:
        next_url = request.registry.api_url + 'tenders?mode=_all_&feed=changes&descending=1&opt_fields=status,auctionPeriod,next_check'
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
            process_listing(json['data'], scheduler, callback_url)
            sleep(0.1)
        except:
            break
    run_date = get_now() + timedelta(minutes=1)
    scheduler.add_job(push, 'date', run_date=run_date, timezone=TZ,
                      id='resync_all', name="Resync all", misfire_grace_time=60 * 60,
                      args=[callback_url + 'resync_all', {'url': next_url}],
                      replace_existing=True)
    return next_url


def resync_tenders_back(request):
    next_url = request.params.get('url', '')
    if not next_url:
        next_url = request.registry.api_url + 'tenders?mode=_all_&feed=changes&descending=1&opt_fields=status,auctionPeriod,next_check'
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
            json = r.json()
            next_url = json['next_page']['uri']
            if not json['data']:
                return next_url
            process_listing(json['data'], scheduler, callback_url)
            sleep(0.1)
        except:
            break
    run_date = get_now() + timedelta(minutes=1)
    scheduler.add_job(push, 'date', run_date=run_date, timezone=TZ,
                      id='resync_back', name="Resync back", misfire_grace_time=60 * 60,
                      args=[callback_url + 'resync_back', {'url': next_url}],
                      replace_existing=True)
    return next_url
