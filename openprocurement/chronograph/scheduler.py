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


def set_holiday(db, day, calendar_id=CALENDAR_ID):
    calendar = get_calendar(db)
    key = parse_date(day).date().isoformat()
    calendar[key] = True
    db.save(calendar)


def delete_holiday(db, day, calendar_id=CALENDAR_ID):
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


def set_date(db, plan, end_time, cur_stream, auction_id, start_time):
    plan['time'] = end_time.isoformat()
    plan['streams'] = cur_stream
    stream_id = 'stream_{}'.format(cur_stream)
    stream = plan.get(stream_id, {})
    stream[start_time.isoformat()] = auction_id
    plan[stream_id] = stream
    db.save(plan)


def calc_auction_end_time(bids, start):
    end = start + bids * BIDDER_TIME + SERVICE_TIME + MIN_PAUSE
    seconds = (end - TZ.localize(datetime.combine(end, WORKING_DAY_START))).seconds
    roundTo = ROUNDING.seconds
    rounding = (seconds + roundTo - 1) // roundTo * roundTo
    return (end + timedelta(0, rounding - seconds, -end.microsecond)).astimezone(TZ)


def planning_auction(auction, start, db, quick=False, lot_id=None):
    tid = auction.get('id', '')
    mode = auction.get('mode', '')
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
        # end = calc_auction_end_time(auction.get('numberOfBids', len(auction.get('bids', []))), start)
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


def check_auction(request, auction, db):
    enquiryPeriodEnd = auction.get('enquiryPeriod', {}).get('endDate')
    enquiryPeriodEnd = enquiryPeriodEnd and parse_date(enquiryPeriodEnd, TZ).astimezone(TZ)
    tenderPeriodStart = auction.get('tenderPeriod', {}).get('startDate')
    tenderPeriodStart = tenderPeriodStart and parse_date(tenderPeriodStart, TZ).astimezone(TZ)
    tenderPeriodEnd = auction.get('tenderPeriod', {}).get('endDate')
    tenderPeriodEnd = tenderPeriodEnd and parse_date(tenderPeriodEnd, TZ).astimezone(TZ)
    now = get_now()
    if auction['status'] == 'active.enquiries' and not tenderPeriodStart and enquiryPeriodEnd and enquiryPeriodEnd <= now:
        LOGGER.info('Switched auction {} to {}'.format(auction['id'], 'active.tendering'),
                    extra=context_unpack(request, {'MESSAGE_ID': 'switched_auction_active.tendering'}))
        return {'status': 'active.tendering'}, now
    elif auction['status'] == 'active.enquiries' and tenderPeriodStart and tenderPeriodStart <= now:
        LOGGER.info('Switched auction {} to {}'.format(auction['id'], 'active.tendering'),
                    extra=context_unpack(request, {'MESSAGE_ID': 'switched_auction_active.tendering'}))
        return {'status': 'active.tendering'}, now
    elif not auction.get('lots') and auction['status'] == 'active.tendering' and not auction.get('auctionPeriod') and tenderPeriodEnd and tenderPeriodEnd > now:
        planned = False
        quick = environ.get('SANDBOX_MODE', False) and u'quick' in auction.get('submissionMethodDetails', '')
        while not planned:
            try:
                auctionPeriod, stream, skip_days = planning_auction(auction, tenderPeriodEnd, db, quick)
                planned = True
            except ResourceConflict:
                planned = False
        auctionPeriod = randomize(auctionPeriod).isoformat()
        LOGGER.info('Planned auction for auction {} to {}. Stream {}.{}'.format(auction['id'], auctionPeriod, stream, skipped_days(skip_days)),
                    extra=context_unpack(request,
                                         {'MESSAGE_ID': 'planned_auction_auction'},
                                         {'PLANNED_DATE': auctionPeriod, 'PLANNED_STREAM': stream, 'PLANNED_DAYS_SKIPPED': skip_days}))
        return {'auctionPeriod': {'startDate': auctionPeriod}}, now
    elif auction.get('lots') and auction['status'] == 'active.tendering' and any([not lot.get('auctionPeriod') for lot in auction['lots'] if lot['status'] == 'active']) and tenderPeriodEnd and tenderPeriodEnd > now:
        quick = environ.get('SANDBOX_MODE', False) and u'quick' in auction.get('submissionMethodDetails', '')
        lots = []
        for lot in auction.get('lots', []):
            if lot['status'] != 'active' or lot.get('auctionPeriod'):
                lots.append({})
                continue
            lot_id = lot['id']
            planned = False
            while not planned:
                try:
                    auctionPeriod, stream, skip_days = planning_auction(auction, tenderPeriodEnd, db, quick, lot_id)
                    planned = True
                except ResourceConflict:
                    planned = False
            auctionPeriod = randomize(auctionPeriod).isoformat()
            lots.append({'auctionPeriod': {'startDate': auctionPeriod}})
            LOGGER.info('Planned auction for lot {} of auction {} to {}. Stream {}.{}'.format(lot_id, auction['id'], auctionPeriod, stream, skipped_days(skip_days)),
                        extra=context_unpack(request,
                                             {'MESSAGE_ID': 'planned_auction_lot'},
                                             {'PLANNED_DATE': auctionPeriod, 'PLANNED_STREAM': stream, 'PLANNED_DAYS_SKIPPED': skip_days, 'LOT_ID': lot_id}))
        return {'lots': lots}, now
    elif not auction.get('lots') and auction['status'] == 'active.tendering' and tenderPeriodEnd and tenderPeriodEnd <= now:
        LOGGER.info('Switched auction {} to {}'.format(auction['id'], 'active.auction'),
                    extra=context_unpack(request, {'MESSAGE_ID': 'switched_auction_active.auction'}))
        return {
            'status': 'active.auction',
            'auctionPeriod': {'startDate': None} if auction.get('numberOfBids', 0) < 2 else {}
        }, now
    elif auction.get('lots') and auction['status'] == 'active.tendering' and tenderPeriodEnd and tenderPeriodEnd <= now:
        LOGGER.info('Switched auction {} to {}'.format(auction['id'], 'active.auction'),
                    extra=context_unpack(request, {'MESSAGE_ID': 'switched_auction_active.auction'}))
        return {
            'status': 'active.auction',
            'lots': [
                {'auctionPeriod': {'startDate': None}} if i.get('numberOfBids', 0) < 2 else {}
                for i in auction.get('lots', [])
            ]
        }, now
    elif not auction.get('lots') and auction['status'] == 'active.auction' and not auction.get('auctionPeriod'):
        planned = False
        quick = environ.get('SANDBOX_MODE', False) and u'quick' in auction.get('submissionMethodDetails', '')
        while not planned:
            try:
                auctionPeriod, stream, skip_days = planning_auction(auction, tenderPeriodEnd, db, quick)
                planned = True
            except ResourceConflict:
                planned = False
        auctionPeriod = randomize(auctionPeriod).isoformat()
        LOGGER.info('Planned auction for auction {} to {}. Stream {}.{}'.format(auction['id'], auctionPeriod, stream, skipped_days(skip_days)),
                    extra=context_unpack(request,
                                         {'MESSAGE_ID': 'planned_auction_auction'},
                                         {'PLANNED_DATE': auctionPeriod, 'PLANNED_STREAM': stream, 'PLANNED_DAYS_SKIPPED': skip_days}))
        return {'auctionPeriod': {'startDate': auctionPeriod}}, now
    elif not auction.get('lots') and auction['status'] == 'active.auction' and auction.get('auctionPeriod'):
        auctionAuctionStart = parse_date(auction.get('auctionPeriod', {}).get('startDate'), TZ).astimezone(TZ)
        auctionAuctionEnd = calc_auction_end_time(auction.get('numberOfBids', len(auction.get('bids', []))), auctionAuctionStart)
        if now > auctionAuctionEnd + MIN_PAUSE:
            planned = False
            quick = environ.get('SANDBOX_MODE', False) and u'quick' in auction.get('submissionMethodDetails', '')
            while not planned:
                try:
                    auctionPeriod, stream, skip_days = planning_auction(auction, now, db, quick)
                    planned = True
                except ResourceConflict:
                    planned = False
            auctionPeriod = randomize(auctionPeriod).isoformat()
            LOGGER.info('Replanned auction for auction {} to {}. Stream {}.{}'.format(auction['id'], auctionPeriod, stream, skipped_days(skip_days)),
                        extra=context_unpack(request,
                                             {'MESSAGE_ID': 'replanned_auction_auction'},
                                             {'PLANNED_DATE': auctionPeriod, 'PLANNED_STREAM': stream, 'PLANNED_DAYS_SKIPPED': skip_days}))
            return {'auctionPeriod': {'startDate': auctionPeriod}}, now
        else:
            return None, auctionAuctionEnd + MIN_PAUSE
    elif auction.get('lots') and auction['status'] == 'active.auction' and any([not lot.get('auctionPeriod') for lot in auction['lots'] if lot['status'] == 'active']):
        quick = environ.get('SANDBOX_MODE', False) and u'quick' in auction.get('submissionMethodDetails', '')
        lots = []
        for lot in auction.get('lots', []):
            if lot['status'] != 'active' or lot.get('auctionPeriod'):
                lots.append({})
                continue
            lot_id = lot['id']
            planned = False
            while not planned:
                try:
                    auctionPeriod, stream, skip_days = planning_auction(auction, tenderPeriodEnd, db, quick, lot_id)
                    planned = True
                except ResourceConflict:
                    planned = False
            auctionPeriod = randomize(auctionPeriod).isoformat()
            lots.append({'auctionPeriod': {'startDate': auctionPeriod}})
            LOGGER.info('Planned auction for lot {} of auction {} to {}. Stream {}.{}'.format(lot_id, auction['id'], auctionPeriod, stream, skipped_days(skip_days)),
                        extra=context_unpack(request,
                                             {'MESSAGE_ID': 'planned_auction_lot'},
                                             {'PLANNED_DATE': auctionPeriod, 'PLANNED_STREAM': stream, 'PLANNED_DAYS_SKIPPED': skip_days, 'LOT_ID': lot_id}))
        return {'lots': lots}, now
    elif auction.get('lots') and auction['status'] == 'active.auction':
        quick = environ.get('SANDBOX_MODE', False) and u'quick' in auction.get('submissionMethodDetails', '')
        lots = []
        lots_ends = []
        for lot in auction.get('lots', []):
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
                        auctionPeriod, stream, skip_days = planning_auction(auction, now, db, quick, lot_id)
                        planned = True
                    except ResourceConflict:
                        planned = False
                auctionPeriod = randomize(auctionPeriod).isoformat()
                lots.append({'auctionPeriod': {'startDate': auctionPeriod}})
                LOGGER.info('Replanned auction for lot {} of auction {} to {}. Stream {}.{}'.format(lot_id, auction['id'], auctionPeriod, stream, skipped_days(skip_days)),
                            extra=context_unpack(request,
                                                 {'MESSAGE_ID': 'replanned_auction_lot'},
                                                 {'PLANNED_DATE': auctionPeriod, 'PLANNED_STREAM': stream, 'PLANNED_DAYS_SKIPPED': skip_days, 'LOT_ID': lot_id}))
            else:
                lots_ends.append(lotAuctionEnd + MIN_PAUSE)
        if any(lots):
            return {'lots': lots}, now
        else:
            return None, min(lots_ends)
    elif not auction.get('lots') and auction['status'] == 'active.awarded':
        standStillEnds = [
            parse_date(a['complaintPeriod']['endDate'], TZ).astimezone(TZ)
            for a in auction.get('awards', [])
            if a.get('complaintPeriod', {}).get('endDate')
        ]
        if not standStillEnds:
            return None, None
        standStillEnd = max(standStillEnds)
        if standStillEnd <= now:
            pending_complaints = any([
                i['status'] == 'pending'
                for i in auction.get('complaints', [])
            ])
            pending_awards_complaints = any([
                i['status'] == 'pending'
                for a in auction.get('awards', [])
                for i in a.get('complaints', [])
            ])
            awarded = any([
                i['status'] == 'active'
                for i in auction.get('awards', [])
            ])
            if not pending_complaints and not pending_awards_complaints and not awarded:
                LOGGER.info('Switched auction {} to {}'.format(auction['id'], 'unsuccessful'),
                            extra=context_unpack(request, {'MESSAGE_ID': 'switched_auction_unsuccessful'}))
                return {'id': auction['id']}, None
        elif standStillEnd > now:
            return None, standStillEnd
    elif auction.get('lots') and auction['status'] in ['active.qualification', 'active.awarded']:
        pending_complaints = any([
            i['status'] == 'pending'
            for i in auction.get('complaints', [])
        ])
        if pending_complaints:
            return None, None
        lots_ends = []
        for lot in auction.get('lots', []):
            if lot['status'] != 'active':
                continue
            lot_awards = [i for i in auction['awards'] if i.get('lotID') == lot['id']]
            standStillEnds = [
                parse_date(a['complaintPeriod']['endDate'], TZ).astimezone(TZ)
                for a in lot_awards
                if a.get('complaintPeriod', {}).get('endDate')
            ]
            if not standStillEnds:
                continue
            standStillEnd = max(standStillEnds)
            if standStillEnd <= now:
                pending_awards_complaints = any([
                    i['status'] == 'pending'
                    for a in lot_awards
                    for i in a.get('complaints', [])
                ])
                awarded = any([
                    i['status'] == 'active'
                    for i in lot_awards
                ])
                if not pending_complaints and not pending_awards_complaints and not awarded:
                    LOGGER.info('Switched lot {} of auction {} to {}'.format(lot['id'], auction['id'], 'unsuccessful'),
                                extra=context_unpack(request, {'MESSAGE_ID': 'switched_lot_unsuccessful'}, {'LOT_ID': lot['id']}))
                    return {'id': auction['id']}, None
            elif standStillEnd > now:
                lots_ends.append(standStillEnd)
        if lots_ends:
            return None, min(lots_ends)
    if enquiryPeriodEnd and enquiryPeriodEnd > now:
        return None, enquiryPeriodEnd
    elif tenderPeriodStart and tenderPeriodStart > now:
        return None, tenderPeriodStart
    elif tenderPeriodEnd and tenderPeriodEnd > now:
        return None, tenderPeriodEnd
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


def resync_auction(request):
    auction_id = request.matchdict['auction_id']
    scheduler = request.registry.scheduler
    url = request.registry.api_url + 'auctions/' + auction_id
    api_token = request.registry.api_token
    callback_url = request.registry.callback_url + 'resync/' + auction_id
    db = request.registry.db
    request_id = request.environ.get('REQUEST_ID', '')
    r = get_request(url, auth=(api_token, ''), headers={'X-Client-Request-ID': request_id})
    if r.status_code != requests.codes.ok:
        LOGGER.error("Error {} on getting auction '{}': {}".format(r.status_code, url, r.text),
                     extra=context_unpack(request, {'MESSAGE_ID': 'error_get_auction'}, {'ERROR_STATUS': r.status_code}))
        if r.status_code == requests.codes.not_found:
            return
        changes = None
        next_check = get_now() + timedelta(minutes=1)
    else:
        json = r.json()
        auction = json['data']
        changes, next_check = check_auction(request, auction, db)
        if changes:
            data = dumps({'data': changes})
            r = SESSION.patch(url,
                              data=data,
                              headers={'Content-Type': 'application/json', 'X-Client-Request-ID': request_id},
                              auth=(api_token, ''))
            if r.status_code != requests.codes.ok:
                LOGGER.error("Error {} on updating auction '{}' with '{}': {}".format(r.status_code, url, data, r.text),
                             extra=context_unpack(request, {'MESSAGE_ID': 'error_patch_auction'}, {'ERROR_STATUS': r.status_code}))
                next_check = get_now() + timedelta(minutes=1)
            elif r.json() and not r.json()['data']['status'].startswith('active'):
                next_check = None
    if next_check:
        scheduler.add_job(push, 'date', run_date=next_check, timezone=TZ,
                          id=auction_id, name="Resync {}".format(auction_id), misfire_grace_time=60 * 60,
                          args=[callback_url, None], replace_existing=True)
    return next_check and next_check.isoformat()


def resync_auctions(request):
    next_url = request.params.get('url', '')
    if not next_url:
        next_url = request.registry.api_url + 'auctions?mode=_all_&feed=changes&descending=1&opt_fields=status'
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
            for auction in json['data']:
                if not auction.get('status', 'active').startswith('active'):
                    continue
                resync_job = scheduler.get_job(auction['id'])
                run_date = get_now()
                if not resync_job or resync_job.next_run_time > run_date + timedelta(minutes=1):
                    scheduler.add_job(push, 'date', run_date=run_date, timezone=TZ,
                                      id=auction['id'], name="Resync {}".format(auction['id']), misfire_grace_time=60 * 60,
                                      args=[callback_url + 'resync/' + auction['id'], None],
                                      replace_existing=True)
            sleep(0.1)
        except:
            break
    run_date = get_now() + timedelta(minutes=1)
    scheduler.add_job(push, 'date', run_date=run_date, timezone=TZ,
                      id='resync_all', name="Resync all", misfire_grace_time=60 * 60,
                      args=[callback_url + 'resync_all', {'url': next_url}],
                      replace_existing=True)
    return next_url


def resync_auctions_back(request):
    next_url = request.params.get('url', '')
    if not next_url:
        next_url = request.registry.api_url + 'auctions?mode=_all_&feed=changes&descending=1&opt_fields=status'
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
            for auction in json['data']:
                if not auction.get('status', 'active').startswith('active'):
                    continue
                resync_job = scheduler.get_job(auction['id'])
                run_date = get_now()
                if not resync_job or resync_job.next_run_time > run_date + timedelta(minutes=1):
                    scheduler.add_job(push, 'date', run_date=run_date, timezone=TZ,
                                      id=auction['id'], name="Resync {}".format(auction['id']), misfire_grace_time=60 * 60,
                                      args=[callback_url + 'resync/' + auction['id'], None],
                                      replace_existing=True)
            sleep(0.1)
        except:
            break
    run_date = get_now() + timedelta(minutes=1)
    scheduler.add_job(push, 'date', run_date=run_date, timezone=TZ,
                      id='resync_back', name="Resync back", misfire_grace_time=60 * 60,
                      args=[callback_url + 'resync_back', {'url': next_url}],
                      replace_existing=True)
    return next_url
