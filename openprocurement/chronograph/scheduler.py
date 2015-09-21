# -*- coding: utf-8 -*-
import os
import requests
from datetime import datetime, timedelta, time
from json import dumps
from pytz import timezone
from iso8601 import parse_date
from couchdb.http import ResourceConflict
from time import sleep
from random import randint
from logging import getLogger


LOG = getLogger(__name__)
TZ = timezone(os.environ['TZ'] if 'TZ' in os.environ else 'Europe/Kiev')
CALENDAR_ID = 'calendar'
STREAMS_ID = 'streams'
WORKING_DAY_START = time(11, 0)
WORKING_DAY_END = time(16, 0)
ROUNDING = timedelta(minutes=15)
MIN_PAUSE = timedelta(minutes=3)
BIDDER_TIME = timedelta(minutes=6)
SERVICE_TIME = timedelta(minutes=9)
STAND_STILL_TIME = timedelta(days=1)


def get_now():
    return TZ.localize(datetime.now())


def randomize(dt):
    return dt + timedelta(seconds=randint(0,900))


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
    return plan_date.time(), plan.get('streams', 1)


def set_date(db, mode, date, time, stream):
    plan_id = 'plan{}_{}'.format(mode, date.isoformat())
    plan = db.get(plan_id, {'_id': plan_id})
    plan['time'] = time.isoformat()
    plan['streams'] = stream
    db.save(plan)


def calc_auction_end_time(bids, start):
    end = start + bids * BIDDER_TIME + SERVICE_TIME + MIN_PAUSE
    seconds = (end - TZ.localize(datetime.combine(end, WORKING_DAY_START))).seconds
    roundTo = ROUNDING.seconds
    rounding = (seconds + roundTo - 1) // roundTo * roundTo
    return (end + timedelta(0, rounding - seconds, -end.microsecond)).astimezone(TZ)


def planning_auction(tender, start, db, quick=False):
    mode = tender.get('mode', '')
    calendar = get_calendar(db)
    streams = get_streams(db)
    if quick:
        quick_start = calc_auction_end_time(0, start)
        return {'startDate': quick_start.isoformat()}
    start += timedelta(hours=1)
    if start.time() < WORKING_DAY_START:
        nextDate = start.date()
    else:
        nextDate = start.date() + timedelta(days=1)
    while True:
        if calendar.get(nextDate.isoformat()) or nextDate.weekday() in [5, 6]:  # skip Saturday and Sunday
            nextDate += timedelta(days=1)
            continue
        dayStart, stream = get_date(db, mode, nextDate)
        if dayStart >= WORKING_DAY_END and stream >= streams:
            nextDate += timedelta(days=1)
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
    #for n in range((end.date() - start.date()).days):
        #date = start.date() + timedelta(n)
        #_, dayStream = get_date(db, mode, date.date())
        #set_date(db, mode, date.date(), WORKING_DAY_END, dayStream+1)
    set_date(db, mode, end.date(), end.time(), stream)
    return start


def check_tender(tender, db):
    enquiryPeriodEnd = tender.get('enquiryPeriod', {}).get('endDate')
    enquiryPeriodEnd = enquiryPeriodEnd and parse_date(enquiryPeriodEnd, TZ).astimezone(TZ)
    tenderPeriodStart = tender.get('tenderPeriod', {}).get('startDate')
    tenderPeriodStart = tenderPeriodStart and parse_date(tenderPeriodStart, TZ).astimezone(TZ)
    tenderPeriodEnd = tender.get('tenderPeriod', {}).get('endDate')
    tenderPeriodEnd = tenderPeriodEnd and parse_date(tenderPeriodEnd, TZ).astimezone(TZ)
    awardPeriodEnd = tender.get('awardPeriod', {}).get('endDate')
    awardPeriodEnd = awardPeriodEnd and parse_date(awardPeriodEnd, TZ).astimezone(TZ)
    standStillEnds = [
        parse_date(a['complaintPeriod']['endDate'], TZ).astimezone(TZ)
        for a in tender.get('awards', [])
        if a.get('complaintPeriod', {}).get('endDate')
    ]
    standStillEnd = max(standStillEnds) if standStillEnds else None
    now = get_now()
    if tender['status'] == 'active.enquiries' and not tenderPeriodStart and enquiryPeriodEnd and enquiryPeriodEnd <= now:
        LOG.info('Switched tender {} to {}'.format(tender['id'], 'active.tendering'))
        return {'status': 'active.tendering'}, now
    elif tender['status'] == 'active.enquiries' and tenderPeriodStart and tenderPeriodStart <= now:
        LOG.info('Switched tender {} to {}'.format(tender['id'], 'active.tendering'))
        return {'status': 'active.tendering'}, now
    elif tender['status'] == 'active.tendering' and not tender.get('auctionPeriod') and tenderPeriodEnd and tenderPeriodEnd > now:
        planned = False
        quick = os.environ.get('SANDBOX_MODE', False) and u'quick' in tender.get('submissionMethodDetails', '')
        while not planned:
            try:
                auctionPeriod = planning_auction(tender, tenderPeriodEnd, db, quick)
                planned = True
            except ResourceConflict:
                planned = False
        auctionPeriod = randomize(auctionPeriod).isoformat()
        LOG.info('Planned auction for tender {} to {}'.format(tender['id'], auctionPeriod))
        return {'auctionPeriod': {'startDate': auctionPeriod}}, now
    elif tender['status'] == 'active.tendering' and tenderPeriodEnd and tenderPeriodEnd <= now:
        numberOfBids = tender.get('numberOfBids', len(tender.get('bids', [])))
        if numberOfBids > 1:
            LOG.info('Switched tender {} to {}'.format(tender['id'], 'active.auction'))
            return {'status': 'active.auction'}, now
        elif numberOfBids == 1:
            LOG.info('Switched tender {} to {}'.format(tender['id'], 'active.qualification'))
            return {'status': 'active.qualification', 'auctionPeriod': {'startDate': None}, 'awardPeriod': {'startDate': now.isoformat()}}, now
        else:
            LOG.info('Switched tender {} to {}'.format(tender['id'], 'unsuccessful'))
            return {'status': 'unsuccessful', 'auctionPeriod': {'startDate': None}}, None
    elif tender['status'] == 'active.auction' and not tender.get('auctionPeriod'):
        planned = False
        quick = os.environ.get('SANDBOX_MODE', False) and u'quick' in tender.get('submissionMethodDetails', '')
        while not planned:
            try:
                auctionPeriod = planning_auction(tender, tenderPeriodEnd, db, quick)
                planned = True
            except ResourceConflict:
                planned = False
        auctionPeriod = randomize(auctionPeriod).isoformat()
        LOG.info('Planned auction for tender {} to {}'.format(tender['id'], auctionPeriod))
        return {'auctionPeriod': {'startDate': auctionPeriod}}, now
    elif tender['status'] == 'active.auction' and tender.get('auctionPeriod'):
        tenderAuctionStart = parse_date(tender.get('auctionPeriod', {}).get('startDate'), TZ).astimezone(TZ)
        tenderAuctionEnd = calc_auction_end_time(tender.get('numberOfBids', len(tender.get('bids', []))), tenderAuctionStart)
        if now > tenderAuctionEnd + MIN_PAUSE:
            planned = False
            quick = os.environ.get('SANDBOX_MODE', False) and u'quick' in tender.get('submissionMethodDetails', '')
            while not planned:
                try:
                    auctionPeriod = planning_auction(tender, now, db, quick)
                    planned = True
                except ResourceConflict:
                    planned = False
            auctionPeriod = randomize(auctionPeriod).isoformat()
            LOG.info('Replanned auction for tender {} to {}'.format(tender['id'], auctionPeriod))
            return {'auctionPeriod': {'startDate': auctionPeriod}}, now
        else:
            return None, tenderAuctionEnd + MIN_PAUSE
    elif tender['status'] == 'active.awarded' and standStillEnd and standStillEnd <= now:
        pending_complaints = [
            i
            for i in tender.get('complaints', [])
            if i['status'] == 'pending'
        ]
        pending_awards_complaints = [
            i
            for a in tender.get('awards', [])
            for i in a.get('complaints', [])
            if i['status'] == 'pending'
        ]
        awarded = [
            i
            for i in tender.get('awards', [])
            if i['status'] == 'active'
        ]
        if not pending_complaints and not pending_awards_complaints and not awarded:
            LOG.info('Switched tender {} to {}'.format(tender['id'], 'unsuccessful'))
            return {'status': 'unsuccessful'}, None
    if enquiryPeriodEnd and enquiryPeriodEnd > now:
        return None, enquiryPeriodEnd
    elif tenderPeriodStart and tenderPeriodStart > now:
        return None, tenderPeriodStart
    elif tenderPeriodEnd and tenderPeriodEnd > now:
        return None, tenderPeriodEnd
    elif awardPeriodEnd and standStillEnd > now:
        return None, standStillEnd
    return None, None


def get_request(url, auth, headers=None):
    tx = ty = 1
    while True:
        try:
            r = requests.get(url, auth=auth, headers=headers)
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


def resync_tender(scheduler, url, api_token, callback_url, db, tender_id, request_id):
    r = get_request(url, auth=(api_token, ''), headers={'X-Client-Request-ID': request_id})
    if r.status_code != requests.codes.ok:
        LOG.error("Error {} on getting tender '{}': {}".format(r.status_code, url, r.text))
        if r.status_code == requests.codes.not_found:
            return
        changes = None
        next_check = get_now() + timedelta(minutes=1)
    else:
        json = r.json()
        tender = json['data']
        changes, next_check = check_tender(tender, db)
        if changes:
            data = dumps({'data': changes})
            r = requests.patch(url,
                               data=data,
                               headers={'Content-Type': 'application/json', 'X-Client-Request-ID': request_id},
                               auth=(api_token, ''))
            if r.status_code != requests.codes.ok:
                LOG.error("Error {} on updating tender '{}' with '{}': {}".format(r.status_code, url, data, r.text))
                next_check = get_now() + timedelta(minutes=1)
    if next_check:
        scheduler.add_job(push, 'date', run_date=next_check, timezone=TZ,
                          id=tender_id, name="Resync {}".format(tender_id), misfire_grace_time=60 * 60,
                          args=[callback_url, None], replace_existing=True)
    return next_check and next_check.isoformat()


def resync_tenders(scheduler, next_url, api_token, callback_url, request_id):
    while True:
        try:
            r = get_request(next_url, auth=(api_token, ''), headers={'X-Client-Request-ID': request_id})
            if r.status_code != requests.codes.ok:
                break
            json = r.json()
            next_url = json['next_page']['uri']
            if not json['data']:
                break
            for tender in json['data']:
                resync_job = scheduler.get_job(tender['id'])
                run_date = get_now()
                if not resync_job or resync_job.next_run_time > run_date + timedelta(minutes=1):
                    scheduler.add_job(push, 'date', run_date=run_date, timezone=TZ,
                                      id=tender['id'], name="Resync {}".format(tender['id']), misfire_grace_time=60 * 60,
                                      args=[callback_url + 'resync/' + tender['id'], None],
                                      replace_existing=True)
        except:
            break
    run_date = get_now() + timedelta(minutes=1)
    scheduler.add_job(push, 'date', run_date=run_date, timezone=TZ,
                      id='resync_all', name="Resync all", misfire_grace_time=60 * 60,
                      args=[callback_url + 'resync_all', {'url': next_url}],
                      replace_existing=True)
    return next_url
