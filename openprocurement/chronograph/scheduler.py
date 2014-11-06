# -*- coding: utf-8 -*-
import requests
from datetime import datetime, timedelta
from json import dumps
from pytz import utc
from time import time


def check_tender(tender):
    now = datetime.now().isoformat()
    enquiryPeriodEnd = tender.get('enquiryPeriod', {}).get('endDate')
    tenderPeriodEnd = tender.get('tenderPeriod', {}).get('endDate')
    if tender['status'] == 'enquiries' and enquiryPeriodEnd and enquiryPeriodEnd < now:
        return {'status': 'tendering'}, None
    elif tender['status'] == 'tendering' and tenderPeriodEnd and tenderPeriodEnd < now:
        return {'status': 'auction'}, None
    ts = time()
    offset = datetime.fromtimestamp(ts) - datetime.utcfromtimestamp(ts)
    if enquiryPeriodEnd and enquiryPeriodEnd > now:
        return None, datetime.strptime(enquiryPeriodEnd, '%Y-%m-%dT%H:%M:%S.%f') - offset
    elif tenderPeriodEnd and tenderPeriodEnd > now:
        return None, datetime.strptime(tenderPeriodEnd, '%Y-%m-%dT%H:%M:%S.%f') - offset
    return None, None


def push(url, params):
    requests.get(url, params=params)


def resync_tender(scheduler, url, callback_url):
    r = requests.get(url)
    json = r.json()
    tender = json['data']
    changes, next_check = check_tender(tender)
    if changes:
        r = requests.patch(url,
                           data=dumps({'data': changes}),
                           headers={'Content-Type': 'application/json'})
    if next_check:
        scheduler.add_job(push, 'date', run_date=next_check, timezone=utc,
                          id=tender['id'],
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
            for tender in json['data'][:2]:
                run_date = datetime.utcfromtimestamp(time())
                scheduler.add_job(push, 'date', run_date=run_date, timezone=utc,
                                  id=tender['id'],
                                  args=[callback_url + 'resync/' + tender['id'], None],
                                  replace_existing=True)
        except:
            break
    run_date = datetime.utcfromtimestamp(time()) + timedelta(seconds=60)
    scheduler.add_job(push, 'date', run_date=run_date, timezone=utc,
                      id='resync_all',
                      args=[callback_url + 'resync_all', {'url': next_url}],
                      replace_existing=True)
    return next_url
