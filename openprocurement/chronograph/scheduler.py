# -*- coding: utf-8 -*-
import requests
from datetime import datetime, timedelta, time
from json import dumps
from pytz import timezone
from tzlocal import get_localzone
from iso8601 import parse_date
from couchdb.http import ResourceConflict


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


def planning_auction(tender, start, db):
    plan = db.get('plan', {'_id': 'plan'})
    if start.timetz() < WORKING_DAY_START:
        nextDate = start.date()
    else:
        nextDate = start.date() + timedelta(days=1)
    while True:
        dayStart = get_date(plan, nextDate)
        if dayStart >= WORKING_DAY_END:
            nextDate += timedelta(days=1)
            continue
        start = datetime.combine(nextDate, dayStart)
        end = calc_auction_end_time(len(tender.get('bids', [])), start)
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
    enquiryPeriodEnd = enquiryPeriodEnd and parse_date(
        enquiryPeriodEnd, TZ).astimezone(TZ)
    tenderPeriodEnd = tender.get('tenderPeriod', {}).get('endDate')
    tenderPeriodEnd = tenderPeriodEnd and parse_date(
        tenderPeriodEnd, TZ).astimezone(TZ)
    awardPeriodEnd = tender.get('awardPeriod', {}).get('endDate')
    awardPeriodEnd = awardPeriodEnd and parse_date(awardPeriodEnd, TZ).astimezone(TZ)
    now = get_now()
    if tender['status'] == 'active.enquiries' and enquiryPeriodEnd and enquiryPeriodEnd < now:
        return {'status': 'active.tendering'}, now
    elif tender['status'] == 'active.tendering' and tenderPeriodEnd and tenderPeriodEnd < now:
        if not tender.get('bids', []):
            return {'status': 'unsuccessful'}, None
        else:
            return {'status': 'active.auction'}, now
    elif tender['status'] == 'active.auction' and not tender.get('auctionPeriod'):
        planned = False
        while not planned:
            try:
                auctionPeriod = planning_auction(tender, now, db)
                planned = True
            except ResourceConflict:
                planned = False
        return {'auctionPeriod': auctionPeriod}, now
    elif tender['status'] == 'active.awarded' and awardPeriodEnd and awardPeriodEnd + STAND_STILL_TIME < now:
        accepted_complaints = [
            i
            for i in tender['complaints']
            if i['status'] == 'accepted'
        ]
        accepted_awards_complaints = [
            i
            for a in tender['awards']
            for i in a['complaints']
            if i['status'] == 'accepted'
        ]
        stand_still_time_expired = tender.awardPeriod.endDate + STAND_STILL_TIME < get_now()
        if not accepted_complaints and not accepted_awards_complaints:
            awards = tender.get('awards', [])
            awarded = [i for i in awards if i['status'] == 'active']
            if awarded:
                return {'status': 'complete'}, None
            else:
                return {'status': 'unsuccessful'}, None
    # elif tender['status'] == 'active.auction' and tender.get('auctionPeriod'):
        #tenderAuctionStart = parse_date(tender.get('auctionPeriod', {}).get('startDate'), TZ).astimezone(TZ)
        #tenderAuctionEnd = calc_auction_end_time(len(tender.get('bids', [])), tenderAuctionStart)
        #plan = get_plan(db)
        #plan_date_end = get_date(plan, tenderAuctionEnd.date())
        # if tenderAuctionEnd.timetz() > plan_date_end:
        # for n in range((tenderAuctionEnd.date() - tenderAuctionStart.date()).days):
        #date = tenderAuctionStart.date() + timedelta(n)
        #set_date(plan, date.date(), WORKING_DAY_END)
        #set_date(plan, tenderAuctionEnd.date(), tenderAuctionEnd.timetz())
        # db.save(plan)
    if enquiryPeriodEnd and enquiryPeriodEnd > now:
        return None, enquiryPeriodEnd
    elif tenderPeriodEnd and tenderPeriodEnd > now:
        return None, tenderPeriodEnd
    elif awardPeriodEnd and awardPeriodEnd > now:
        return None, awardPeriodEnd + STAND_STILL_TIME
    return None, None


def push(url, params):
    requests.get(url, params=params)


def resync_tender(scheduler, url, callback_url, db):
    r = requests.get(url)
    json = r.json()
    tender = json['data']
    changes, next_check = check_tender(tender, db)
    if changes:
        r = requests.patch(url,
                           data=dumps({'data': changes}),
                           headers={'Content-Type': 'application/json'})
    if next_check:
        scheduler.add_job(push, 'date', run_date=next_check, timezone=TZ,
                          id=tender['id'], misfire_grace_time=60 * 60,
                          args=[callback_url, None], replace_existing=True)
    return changes, next_check


def resync_tenders(scheduler, next_url, callback_url):
    while True:
        try:
            r = requests.get(next_url)
            json = r.json()
            next_url = json['next_page']['uri']
            if not json['data']:
                break
            for tender in json['data']:
                run_date = get_now()
                scheduler.add_job(push, 'date', run_date=run_date, timezone=TZ,
                                  id=tender['id'], misfire_grace_time=60 * 60,
                                  args=[
                                      callback_url + 'resync/' + tender['id'], None],
                                  replace_existing=True)
        except:
            break
    run_date = get_now() + timedelta(seconds=60)
    scheduler.add_job(push, 'date', run_date=run_date, timezone=TZ,
                      id='resync_all', misfire_grace_time=60 * 60,
                      args=[callback_url + 'resync_all', {'url': next_url}],
                      replace_existing=True)
    return next_url
