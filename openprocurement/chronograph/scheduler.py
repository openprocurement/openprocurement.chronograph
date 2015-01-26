# -*- coding: utf-8 -*-
import os
import requests
from datetime import datetime, timedelta, time
from json import dumps
from pytz import timezone
from tzlocal import get_localzone
from iso8601 import parse_date
from couchdb.http import ResourceConflict
from time import sleep
from logging import getLogger


LOG = getLogger(__name__)
TZ = timezone(get_localzone().tzname(datetime.now()))
WORKING_DAY_START = time(11, 0, tzinfo=TZ)
WORKING_DAY_END = time(16, 0, tzinfo=TZ)
ROUNDING = timedelta(minutes=15)
MIN_PAUSE = timedelta(minutes=5)
BIDDER_TIME = timedelta(minutes=6)
SERVICE_TIME = timedelta(minutes=9)
STAND_STILL_TIME = timedelta(days=10)


def get_now():
    return datetime.now(TZ)


def get_plan(db):
    return db.get('plan', {'_id': 'plan'})


def get_date(plan, date):
    plan_date_end = plan.get(date.isoformat(), WORKING_DAY_START.isoformat())
    plan_date = parse_date('2001-01-01T' + plan_date_end, TZ).astimezone(TZ)
    return plan_date.timetz()


def set_date(plan, date, time):
    plan[date.isoformat()] = time.isoformat()


def calc_auction_end_time(bids, start):
    end = start + bids * BIDDER_TIME + SERVICE_TIME + MIN_PAUSE
    seconds = (end - datetime.combine(end, WORKING_DAY_START)).seconds
    roundTo = ROUNDING.seconds
    rounding = (seconds + roundTo / 2) // roundTo * roundTo
    return end + timedelta(0, rounding - seconds, -end.microsecond)


def planning_auction(tender, start, db, quick=False):
    cpv_group = tender.get('items', [{}])[0].get('classification', {}).get('id')
    plan_id = 'plan_{}'.format(cpv_group[:3]) if cpv_group else 'plan'
    plan = db.get(plan_id, {'_id': plan_id})
    if quick:
        quick_start = calc_auction_end_time(0, start)
        return {'startDate': quick_start.isoformat()}
    elif start.timetz() < WORKING_DAY_START:
        nextDate = start.date()
    else:
        nextDate = start.date() + timedelta(days=1)
    while True:
        dayStart = get_date(plan, nextDate)
        if dayStart >= WORKING_DAY_END:
            nextDate += timedelta(days=1)
            continue
        start = datetime.combine(nextDate, dayStart)
        end = calc_auction_end_time(3, start)  # len(tender.get('bids', [])
        if dayStart == WORKING_DAY_START and end > datetime.combine(nextDate, WORKING_DAY_END):
            break
        elif end <= datetime.combine(nextDate, WORKING_DAY_END):
            break
        nextDate += timedelta(days=1)
    for n in range((end.date() - start.date()).days):
        date = start.date() + timedelta(n)
        set_date(plan, date.date(), WORKING_DAY_END)
    set_date(plan, end.date(), end.timetz())
    db.save(plan)
    return {'startDate': start.isoformat()}


def check_tender(tender, db):
    enquiryPeriodEnd = tender.get('enquiryPeriod', {}).get('endDate')
    enquiryPeriodEnd = enquiryPeriodEnd and parse_date(enquiryPeriodEnd, TZ).astimezone(TZ)
    tenderPeriodStart = tender.get('tenderPeriod', {}).get('startDate')
    tenderPeriodStart = tenderPeriodStart and parse_date(tenderPeriodStart, TZ).astimezone(TZ)
    tenderPeriodEnd = tender.get('tenderPeriod', {}).get('endDate')
    tenderPeriodEnd = tenderPeriodEnd and parse_date(tenderPeriodEnd, TZ).astimezone(TZ)
    awardPeriodEnd = tender.get('awardPeriod', {}).get('endDate')
    awardPeriodEnd = awardPeriodEnd and parse_date(awardPeriodEnd, TZ).astimezone(TZ)
    now = get_now()
    if tender['status'] == 'active.enquiries' and not tenderPeriodStart and enquiryPeriodEnd and enquiryPeriodEnd < now:
        LOG.info('Switched tender {} to {}'.format(tender['id'], 'active.tendering'))
        return {'status': 'active.tendering'}, now
    elif tender['status'] == 'active.enquiries' and tenderPeriodStart and tenderPeriodStart < now:
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
        LOG.info('Planned auction for tender {} to {}'.format(tender['id'], auctionPeriod['startDate']))
        return {'auctionPeriod': auctionPeriod}, now
    elif tender['status'] == 'active.tendering' and tenderPeriodEnd and tenderPeriodEnd < now:
        numberOfBids = tender.get('numberOfBids', len(tender.get('bids', [])))
        if numberOfBids > 1:
            LOG.info('Switched tender {} to {}'.format(tender['id'], 'active.auction'))
            return {'status': 'active.auction'}, now
        elif numberOfBids == 1:
            LOG.info('Switched tender {} to {}'.format(tender['id'], 'active.qualification'))
            return {'status': 'active.qualification', 'auctionPeriod': {'startDate': None}, 'awardPeriod': {'startDate': now.isoformat()}}, now
        else:
            LOG.info('Switched tender {} to {}'.format(tender['id'], 'unsuccessful'))
            return {'status': 'unsuccessful'}, None
    #elif tender['status'] == 'active.auction' and not tender.get('auctionPeriod'):
        #planned = False
        #while not planned:
            #try:
                #auctionPeriod = planning_auction(tender, now, db)
                #planned = True
            #except ResourceConflict:
                #planned = False
        #return {'auctionPeriod': auctionPeriod}, now
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
            LOG.info('Replanned auction for tender {} to {}'.format(tender['id'], auctionPeriod['startDate']))
            return {'auctionPeriod': auctionPeriod}, now
        else:
            return None, tenderAuctionEnd + MIN_PAUSE
    elif tender['status'] == 'active.awarded' and awardPeriodEnd and awardPeriodEnd + STAND_STILL_TIME < now:
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
        if not pending_complaints and not pending_awards_complaints:
            awards = tender.get('awards', [])
            awarded = [i for i in awards if i['status'] == 'active']
            if awarded:
                LOG.info('Switched tender {} to {}'.format(tender['id'], 'complete'))
                return {'status': 'complete'}, None
            else:
                LOG.info('Switched tender {} to {}'.format(tender['id'], 'unsuccessful'))
                return {'status': 'unsuccessful'}, None
    if enquiryPeriodEnd and enquiryPeriodEnd > now:
        return None, enquiryPeriodEnd
    elif tenderPeriodStart and tenderPeriodStart > now:
        return None, tenderPeriodStart
    elif tenderPeriodEnd and tenderPeriodEnd > now:
        return None, tenderPeriodEnd
    elif awardPeriodEnd and awardPeriodEnd > now:
        return None, awardPeriodEnd + STAND_STILL_TIME
    return None, None


def get_request(url, auth):
    while True:
        try:
            r = requests.get(url, auth=auth)
        except:
            pass
        else:
            break
        sleep(60)
    return r


def push(url, params):
    while True:
        try:
            r = requests.get(url, params=params)
        except:
            pass
        else:
            if r.status_code == requests.codes.ok:
                break
        sleep(10)


def resync_tender(scheduler, url, api_token, callback_url, db):
    r = get_request(url, auth=(api_token, ''))
    if r.status_code != requests.codes.ok:
        return
    json = r.json()
    tender = json['data']
    changes, next_check = check_tender(tender, db)
    if changes:
        data = dumps({'data': changes})
        r = requests.patch(url,
                           data=data,
                           headers={'Content-Type': 'application/json'},
                           auth=(api_token, ''))
        if r.status_code != requests.codes.ok:
            LOG.error("Error {} on updating tender '{}' with '{}': {}".format(r.status_code, url, data, r.text))
            next_check = get_now() + timedelta(minutes=1)
    if next_check:
        scheduler.add_job(push, 'date', run_date=next_check, timezone=TZ,
                          id=tender['id'], misfire_grace_time=60 * 60,
                          args=[callback_url, None], replace_existing=True)
    return changes, next_check


def resync_tenders(scheduler, next_url, api_token, callback_url):
    while True:
        try:
            r = get_request(next_url, auth=(api_token, ''))
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
                                      id=tender['id'], misfire_grace_time=60 * 60,
                                      args=[callback_url + 'resync/' + tender['id'], None],
                                      replace_existing=True)
        except:
            break
    run_date = get_now() + timedelta(minutes=1)
    scheduler.add_job(push, 'date', run_date=run_date, timezone=TZ,
                      id='resync_all', misfire_grace_time=60 * 60,
                      args=[callback_url + 'resync_all', {'url': next_url}],
                      replace_existing=True)
    return next_url
