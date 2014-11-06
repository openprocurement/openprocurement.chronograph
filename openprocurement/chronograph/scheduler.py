# -*- coding: utf-8 -*-
import requests
from pytz import utc
import time
from datetime import datetime, timedelta
from json import dumps


def check_tender(tender):
    changes = {'methodJustification': datetime.now().isoformat()}
    next_check = datetime.utcfromtimestamp(time.time()) + timedelta(seconds=10)
    return None, next_check


def push(url, params):
    requests.get(url, params=params)


def resync_tender(scheduler, url, callback_url):
    r = requests.get(url)
    json = r.json()
    tender = json['data']
    print tender
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
                run_date = datetime.utcfromtimestamp(time.time())
                scheduler.add_job(push, 'date', run_date=run_date, timezone=utc,
                                  id=tender['id'],
                                  args=[callback_url + 'resync/' + tender['id'], None],
                                  replace_existing=True)
        except:
            break
    run_date = datetime.utcfromtimestamp(time.time()) + timedelta(seconds=60)
    scheduler.add_job(push, 'date', run_date=run_date, timezone=utc,
                      id='resync_all',
                      args=[callback_url + 'resync_all', {'url': next_url}],
                      replace_existing=True)
    return next_url
