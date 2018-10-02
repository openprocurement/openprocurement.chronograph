# -*- coding: utf-8 -*-
import unittest
from copy import deepcopy
from datetime import datetime, timedelta
from logging import getLogger

from openprocurement.chronograph.utils import get_manager_for_auction
from time import sleep

import requests
from iso8601 import parse_date

from openprocurement.chronograph import TZ
from openprocurement.chronograph.constants import DEFAULT_STREAMS_DOC
from openprocurement.chronograph.tests.utils import update_json
from openprocurement.chronograph.scheduler import planning_auction
from openprocurement.chronograph.tests.base import BaseWebTest, BaseAuctionWebTest
from openprocurement.chronograph.tests.data import test_bids, test_lots, test_auction_data

LOGGER = getLogger(__name__)
test_auction_data_quick = deepcopy(test_auction_data)
test_auction_data_quick.update({
    "enquiryPeriod": {
        'startDate': datetime.now(TZ).isoformat(),
        "endDate": datetime.now(TZ).isoformat()
    },
    'tenderPeriod': {
        'startDate': datetime.now(TZ).isoformat(),
        "endDate": datetime.now(TZ).isoformat()
    }
})
test_auction_data_test_quick = deepcopy(test_auction_data_quick)
test_auction_data_test_quick['mode'] = 'test'


class SimpleTest(BaseWebTest):

    def test_list_jobs(self):
        response = self.app.get('/')
        self.assertEqual(response.status, '200 OK')
        self.assertIn('jobs', response.json)
        self.assertEqual(len(response.json['jobs']), 1)

    def test_resync_all(self):
        response = self.app.get('/resync_all')
        self.assertEqual(response.status, '200 OK')
        self.assertNotEqual(response.json, None)

    def test_resync_back(self):
        response = self.app.get('/resync_back')
        self.assertEqual(response.status, '200 OK')
        self.assertNotEqual(response.json, None)

    def test_resync_one(self):
        response = self.app.get('/resync/all')
        self.assertEqual(response.status, '200 OK')
        self.assertEqual(response.json, None)

    def test_recheck_one(self):
        response = self.app.get('/recheck/all')
        self.assertEqual(response.status, '200 OK')
        self.assertEqual(response.json, None)

    def test_calendar(self):
        response = self.app.get('/calendar')
        self.assertEqual(response.status, '200 OK')
        self.assertEqual(response.json, [])

    def test_calendar_entry(self):
        response = self.app.get('/calendar/2015-04-23')
        self.assertEqual(response.status, '200 OK')
        self.assertEqual(response.json, False)
        response = self.app.post('/calendar/2015-04-23')
        self.assertEqual(response.status, '200 OK')
        self.assertEqual(response.json, True)
        response = self.app.delete('/calendar/2015-04-23')
        self.assertEqual(response.status, '200 OK')
        self.assertEqual(response.json, False)
        response = self.app.get('/calendar/2015-04-23')
        self.assertEqual(response.status, '200 OK')
        self.assertEqual(response.json, False)

    def test_streams(self):
        # GET /streams
        response = self.app.get('/streams')
        self.assertEqual(response.status, '200 OK')
        self.assertEqual(response.json, DEFAULT_STREAMS_DOC['streams'])

        response = self.app.get('/streams?dutch_streams=true')
        self.assertEqual(response.status, '200 OK')
        self.assertEqual(response.json, DEFAULT_STREAMS_DOC['dutch_streams'])

        # POST /streams
        response = self.app.post('/streams', {'streams': 20})
        self.assertEqual(response.status, '200 OK')
        self.assertEqual(response.json, True)

        # GET /streams
        response = self.app.get('/streams')
        self.assertEqual(response.status, '200 OK')
        self.assertEqual(response.json, 20)

        # POST /streams
        response = self.app.post('/streams', {'dutch_streams': 21})
        self.assertEqual(response.status, '200 OK')
        self.assertEqual(response.json, True)

        # GET /streams
        response = self.app.get('/streams?dutch_streams=true')
        self.assertEqual(response.status, '200 OK')
        self.assertEqual(response.json, 21)

        # POST /streams
        response = self.app.post('/streams', {'streams': -20})
        self.assertEqual(response.status, '200 OK')
        self.assertEqual(response.json, False)
        response = self.app.post('/streams', {'dutch_streams': -20})
        self.assertEqual(response.status, '200 OK')
        self.assertEqual(response.json, False)
        response = self.app.post('/streams', {'streams': 11,
                                              'dutch_streams': 12})
        self.assertEqual(response.status, '200 OK')
        self.assertEqual(response.json, True)

        # GET /streams
        response = self.app.get('/streams')
        self.assertEqual(response.status, '200 OK')
        self.assertEqual(response.json, 11)

        response = self.app.get('/streams?dutch_streams=true')
        self.assertEqual(response.status, '200 OK')
        self.assertEqual(response.json, 12)

        # POST /streams
        response = self.app.patch('/streams')
        self.assertEqual(response.status, '200 OK')
        self.assertEqual(response.json, False)


class AuctionsTest(BaseAuctionWebTest):

    def test_list_jobs(self):
        response = self.app.get('/')
        self.assertEqual(response.status, '200 OK')
        self.assertIn('jobs', response.json)
        self.assertEqual(len(response.json['jobs']), 1)
        self.assertIn('resync_all', response.json['jobs'])
        response = self.app.get('/recheck/' + self.auction_id)
        self.assertEqual(response.status, '200 OK')
        self.assertNotEqual(response.json, None)
        response = self.app.get('/')
        self.assertEqual(response.status, '200 OK')
        self.assertIn('jobs', response.json)
        self.assertEqual(len(response.json['jobs']), 2)
        self.assertIn("recheck_{}".format(self.auction_id), response.json['jobs'])

    def test_resync_all(self):
        response = self.app.get('/resync_all')
        self.assertEqual(response.status, '200 OK')
        self.assertNotEqual(response.json, None)
        sleep(0.1)
        response = self.app.get('/')
        self.assertEqual(response.status, '200 OK')
        self.assertIn('jobs', response.json)
        self.assertEqual(len(response.json['jobs']), 2)
        self.assertIn("recheck_{}".format(self.auction_id), response.json['jobs'])


class AuctionTest(BaseAuctionWebTest):
    scheduler = False

    def test_wait_for_enquiryPeriod(self):
        response = self.app.get('/recheck/' + self.auction_id)
        self.assertEqual(response.status, '200 OK')
        self.assertNotEqual(response.json, None)
        response = requests.get('{}/{}'.format(self.app.app.registry.full_url, self.auction_id))
        response.json = response.json()
        auction = response.json['data']
        self.assertEqual(auction['status'], 'active.enquiries')

    def test_switch_to_auctioning_enquiryPeriod(self):
        response = requests.patch('{}/{}'.format(self.app.app.registry.full_url, self.auction_id), {
            'data': {
                "enquiryPeriod": {
                    "endDate": datetime.now(TZ).isoformat()
                },
                'tenderPeriod': {
                    'startDate': None
                }
            }
        })
        response = self.app.get('/recheck/' + self.auction_id)
        self.assertEqual(response.status, '200 OK')
        self.assertNotEqual(response.json, None)
        response = requests.get('{}/{}'.format(self.app.app.registry.full_url, self.auction_id))
        response.json = response.json()
        auction = response.json['data']
        self.assertEqual(auction['status'], 'active.tendering')

    def test_switch_to_auctioning_tenderPeriod(self):
        response = requests.patch('{}/{}'.format(self.app.app.registry.full_url, self.auction_id), {
            'data': {
                "enquiryPeriod": {
                    "endDate": datetime.now(TZ).isoformat()
                },
                'tenderPeriod': {
                    'startDate': datetime.now(TZ).isoformat()
                }
            }
        })
        for _ in range(100):
            response = self.app.get('/recheck/' + self.auction_id)
            self.assertEqual(response.status, '200 OK')
            self.assertNotEqual(response.json, None)
            response = requests.get('{}/{}'.format(self.app.app.registry.full_url, self.auction_id))
            response.json = response.json()
            auction = response.json['data']
            if response.json['data']['status'] == 'active.tendering':
                break
            sleep(0.1)
        self.assertEqual(auction['status'], 'active.tendering')

    def test_wait_for_tenderPeriod(self):
        response = requests.patch('{}/{}'.format(self.app.app.registry.full_url, self.auction_id), {
            'data': {
                "enquiryPeriod": {
                    "endDate": datetime.now(TZ).isoformat()
                },
                'tenderPeriod': {
                    'startDate': (datetime.now(TZ) + timedelta(hours=1)).isoformat()
                }
            }
        })
        response = self.app.get('/recheck/' + self.auction_id)
        self.assertEqual(response.status, '200 OK')
        self.assertNotEqual(response.json, None)
        response = requests.get('{}/{}'.format(self.app.app.registry.full_url, self.auction_id))
        response.json = response.json()
        auction = response.json['data']
        self.assertEqual(auction['status'], 'active.enquiries')

    def test_set_auctionPeriod_jobs(self):
        now = datetime.now(TZ)
        response = requests.patch('{}/{}'.format(self.app.app.registry.full_url, self.auction_id), {
            'data': {
                "enquiryPeriod": {
                    "endDate": now.isoformat()
                },
                'tenderPeriod': {
                    'startDate': now.isoformat(),
                    'endDate': (now + timedelta(days=1)).isoformat()
                }
            }
        })
        for _ in range(100):
            self.app.app.registry.scheduler.start()
            response = self.app.get('/resync_all')
            self.assertEqual(response.status, '200 OK')
            self.assertNotEqual(response.json, None)
            response = self.app.get('/')
            self.app.app.registry.scheduler.shutdown()
            self.assertEqual(response.status, '200 OK')
            self.assertIn('jobs', response.json)
            self.assertEqual(len(response.json['jobs']), 2)
            if "recheck_{}".format(self.auction_id) in response.json['jobs']:
                break
        self.assertIn("recheck_{}".format(self.auction_id), response.json['jobs'])
        response = self.app.get('/recheck/' + self.auction_id)
        self.assertEqual(response.status, '200 OK')
        self.assertNotEqual(response.json, None)
        for _ in range(10):
            self.app.app.registry.scheduler.start()
            self.app.get('/resync_all')
            self.app.app.registry.scheduler.shutdown()

            response = requests.get('{}/{}'.format(self.app.app.registry.full_url, self.auction_id))
            response.json = response.json()
            auction = response.json['data']
            self.assertEqual(auction['status'], 'active.tendering')

            if self.initial_lots:
                self.assertIn('auctionPeriod', auction['lots'][0])
                if 'startDate' in auction['lots'][0]['auctionPeriod']:
                    break
            else:
                self.assertIn('auctionPeriod', auction)
                if 'startDate' in auction['auctionPeriod']:
                    break
        else:
            response = self.app.get('/resync/' + self.auction_id)
            self.assertEqual(response.status, '200 OK')
            self.assertEqual(response.json, None)

        response = requests.get('{}/{}'.format(self.app.app.registry.full_url, self.auction_id))
        response.json = response.json()
        auction = response.json['data']
        self.assertEqual(auction['status'], 'active.tendering')
        if self.initial_lots:
            self.assertIn('startDate', auction['lots'][0]['auctionPeriod'])
        else:
            self.assertIn('startDate', auction['auctionPeriod'])

    def test_set_auctionPeriod_nextday(self):
        now = datetime.now(TZ)
        response = requests.patch('{}/{}'.format(self.app.app.registry.full_url, self.auction_id), {
            'data': {
                "enquiryPeriod": {
                    "endDate": now.isoformat()
                },
                'tenderPeriod': {
                    'startDate': now.isoformat(),
                    'endDate': (now + timedelta(days=7 - now.weekday())).replace(hour=13).isoformat()
                }
            }
        })
        response = self.app.get('/recheck/' + self.auction_id)
        self.assertEqual(response.status, '200 OK')
        self.assertNotEqual(response.json, None)
        response = requests.get('{}/{}'.format(self.app.app.registry.full_url, self.auction_id))
        response.json = response.json()
        auction = response.json['data']
        self.assertEqual(auction['status'], 'active.tendering')
        response = self.app.get('/resync/' + self.auction_id)
        self.assertEqual(response.status, '200 OK')
        self.assertEqual(response.json, None)
        response = requests.get('{}/{}'.format(self.app.app.registry.full_url, self.auction_id))
        response.json = response.json()
        auction = response.json['data']
        self.assertEqual(auction['status'], 'active.tendering')
        if self.initial_lots:
            self.assertIn('auctionPeriod', auction['lots'][0])
            self.assertEqual(parse_date(auction['lots'][0]['auctionPeriod']['startDate'], TZ).weekday(), 1)
        else:
            self.assertIn('auctionPeriod', auction)
            self.assertEqual(parse_date(auction['auctionPeriod']['startDate'], TZ).weekday(), 1)
        response = self.app.get('/recheck/' + self.auction_id)
        self.assertEqual(response.status, '200 OK')
        self.assertNotEqual(response.json, None)
        self.app.app.registry.scheduler.start()
        response = self.app.get('/')
        self.assertEqual(response.status, '200 OK')
        self.assertIn('jobs', response.json)
        self.assertIn('recheck_{}'.format(self.auction_id), response.json['jobs'])
        self.assertGreaterEqual(parse_date(response.json['jobs']["recheck_{}".format(self.auction_id)]).utctimetuple(), parse_date(auction['tenderPeriod']['endDate']).utctimetuple())
        self.assertLessEqual(parse_date(response.json['jobs']["recheck_{}".format(self.auction_id)]).utctimetuple(), (parse_date(auction['tenderPeriod']['endDate']) + timedelta(minutes=5)).utctimetuple())

    def test_set_auctionPeriod_skip_weekend(self):
        now = datetime.now(TZ)
        response = requests.patch('{}/{}'.format(self.app.app.registry.full_url, self.auction_id), {
            'data': {
                "enquiryPeriod": {
                    "endDate": now.isoformat()
                },
                'tenderPeriod': {
                    'startDate': now.isoformat(),
                    'endDate': (now + timedelta(days=5 - now.weekday(), hours=1)).isoformat()
                }
            }
        })
        response = self.app.get('/recheck/' + self.auction_id)
        self.assertEqual(response.status, '200 OK')
        self.assertNotEqual(response.json, None)
        response = requests.get('{}/{}'.format(self.app.app.registry.full_url, self.auction_id))
        response.json = response.json()
        auction = response.json['data']
        self.assertEqual(auction['status'], 'active.tendering')
        response = self.app.get('/resync/' + self.auction_id)
        self.assertEqual(response.status, '200 OK')
        self.assertEqual(response.json, None)
        response = requests.get('{}/{}'.format(self.app.app.registry.full_url, self.auction_id))
        response.json = response.json()
        auction = response.json['data']
        self.assertEqual(auction['status'], 'active.tendering')
        if self.initial_lots:
            self.assertIn('auctionPeriod', auction['lots'][0])
            self.assertEqual(parse_date(auction['lots'][0]['auctionPeriod']['startDate'], TZ).weekday(), 0)
        else:
            self.assertIn('auctionPeriod', auction)
            self.assertEqual(parse_date(auction['auctionPeriod']['startDate'], TZ).weekday(), 0)

    def test_set_auctionPeriod_skip_holidays(self):
        now = datetime.now(TZ)
        today = now.date()
        for i in range(10):
            date = today + timedelta(days=i)
            self.app.post('/calendar/' + date.isoformat())
        calendar = self.app.get('/calendar').json
        response = requests.patch('{}/{}'.format(self.app.app.registry.full_url, self.auction_id), {
            'data': {
                "enquiryPeriod": {
                    "endDate": now.isoformat()
                },
                'tenderPeriod': {
                    'startDate': now.isoformat(),
                    'endDate': (now + timedelta(days=1)).isoformat()
                }
            }
        })
        response = self.app.get('/recheck/' + self.auction_id)
        self.assertEqual(response.status, '200 OK')
        self.assertNotEqual(response.json, None)
        response = requests.get('{}/{}'.format(self.app.app.registry.full_url, self.auction_id))
        response.json = response.json()
        auction = response.json['data']
        self.assertEqual(auction['status'], 'active.tendering')
        response = self.app.get('/resync/' + self.auction_id)
        self.assertEqual(response.status, '200 OK')
        self.assertEqual(response.json, None)
        response = requests.get('{}/{}'.format(self.app.app.registry.full_url, self.auction_id))
        response.json = response.json()
        auction = response.json['data']
        self.assertEqual(auction['status'], 'active.tendering')
        if self.initial_lots:
            self.assertIn('auctionPeriod', auction['lots'][0])
            auctionPeriodstart = parse_date(auction['lots'][0]['auctionPeriod']['startDate'], TZ)
        else:
            self.assertIn('auctionPeriod', auction)
            auctionPeriodstart = parse_date(auction['auctionPeriod']['startDate'], TZ)
        self.assertNotIn(auctionPeriodstart.date().isoformat(), calendar)
        self.assertTrue(auctionPeriodstart.date() > date)

    def test_set_auctionPeriod_today(self):
        now = datetime.now(TZ)
        response = requests.patch('{}/{}'.format(self.app.app.registry.full_url, self.auction_id), {
            'data': {
                "enquiryPeriod": {
                    "endDate": now.isoformat()
                },
                'tenderPeriod': {
                    'startDate': now.isoformat(),
                    'endDate': (now + timedelta(days=7 - now.weekday())).replace(hour=1).isoformat()
                }
            }
        })
        response = self.app.get('/recheck/' + self.auction_id)
        self.assertEqual(response.status, '200 OK')
        self.assertNotEqual(response.json, None)
        response = requests.get('{}/{}'.format(self.app.app.registry.full_url, self.auction_id))
        response.json = response.json()
        auction = response.json['data']
        self.assertEqual(auction['status'], 'active.tendering')
        response = self.app.get('/resync/' + self.auction_id)
        self.assertEqual(response.status, '200 OK')
        self.assertEqual(response.json, None)
        response = requests.get('{}/{}'.format(self.app.app.registry.full_url, self.auction_id))
        response.json = response.json()
        auction = response.json['data']
        self.assertEqual(auction['status'], 'active.tendering')
        if self.initial_lots:
            self.assertIn('auctionPeriod', auction['lots'][0])
            self.assertEqual(parse_date(auction['lots'][0]['auctionPeriod']['startDate'], TZ).weekday(), 1)
        else:
            self.assertIn('auctionPeriod', auction)
            self.assertEqual(parse_date(auction['auctionPeriod']['startDate'], TZ).weekday(), 1)

    def test_switch_to_unsuccessful(self):
        response = requests.patch('{}/{}'.format(self.app.app.registry.full_url, self.auction_id), {
            'data': {
                "enquiryPeriod": {
                    "endDate": datetime.now(TZ).isoformat()
                },
                'tenderPeriod': {
                    'startDate': datetime.now(TZ).isoformat(),
                    "endDate": datetime.now(TZ).isoformat()
                }
            }
        })
        response = self.app.get('/recheck/' + self.auction_id)
        self.assertEqual(response.status, '200 OK')
        self.assertNotEqual(response.json, None)
        response = requests.get('{}/{}'.format(self.app.app.registry.full_url, self.auction_id))
        response.json = response.json()
        auction = response.json['data']
        self.assertEqual(auction['status'], 'active.tendering')
        response = self.app.get('/recheck/' + self.auction_id)
        self.assertEqual(response.status, '200 OK')
        self.assertEqual(response.json, None)
        response = requests.get('{}/{}'.format(self.app.app.registry.full_url, self.auction_id))
        response.json = response.json()
        auction = response.json['data']
        self.assertEqual(auction['status'], 'unsuccessful')


class AuctionLotTest(AuctionTest):
    initial_lots = test_lots


class AuctionTest2(BaseAuctionWebTest):
    scheduler = False
    quick = True
    initial_bids = test_bids[:1]

    def test_switch_to_qualification(self):
        response = self.app.get('/recheck/' + self.auction_id)
        self.assertEqual(response.status, '200 OK')
        self.assertEqual(response.json, None)
        response = requests.get('{}/{}'.format(self.app.app.registry.full_url, self.auction_id))
        response.json = response.json()
        auction = response.json['data']
        self.assertEqual(auction['status'], 'active.qualification')

    def test_switch_to_unsuccessful(self):
        response = self.app.get('/recheck/' + self.auction_id)
        self.assertEqual(response.status, '200 OK')
        self.assertEqual(response.json, None)
        response = requests.get('{}/{}'.format(self.app.app.registry.full_url, self.auction_id))
        response.json = response.json()
        auction = response.json['data']
        self.assertEqual(auction['status'], 'active.qualification')
        self.assertIn('awards', auction)
        award = auction['awards'][0]
        response = requests.patch('{}/{}'.format(self.app.app.registry.full_url, self.auction_id) + '/awards/' + award['id'], {"data": {"status": "unsuccessful"}})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers['Content-type'], 'application/json')
        response = self.app.get('/recheck/' + self.auction_id)
        self.assertEqual(response.status, '200 OK')
        self.assertNotEqual(response.json, None)
        response = requests.get('{}/{}'.format(self.app.app.registry.full_url, self.auction_id))
        response.json = response.json()
        auction = response.json['data']
        self.assertEqual(auction['status'], 'active.awarded')

        response = requests.get('{}/{}'.format(self.app.app.registry.full_url, self.auction_id))
        auction = response.json()['data']
        auction['awards'][0]['complaintPeriod']['endDate'] = datetime.now(TZ).isoformat()
        update_json(self.api, 'auction', self.auction_id, {"data": auction})
        response = self.app.get('/recheck/' + self.auction_id)
        self.assertEqual(response.status, '200 OK')
        self.assertEqual(response.json, None)
        response = requests.get('{}/{}'.format(self.app.app.registry.full_url, self.auction_id))
        response.json = response.json()
        auction = response.json['data']
        self.assertEqual(auction['status'], 'unsuccessful')


class AuctionLotTest2(AuctionTest2):
    initial_lots = test_lots


class AuctionTest3(BaseAuctionWebTest):
    scheduler = False
    quick = True
    initial_bids = test_bids

    def test_switch_to_auction(self):
        response = self.app.get('/recheck/' + self.auction_id)
        self.assertEqual(response.status, '200 OK')
        self.assertEqual(response.json, None)
        response = requests.get('{}/{}'.format(self.app.app.registry.full_url, self.auction_id))
        response.json = response.json()
        auction = response.json['data']
        self.assertEqual(auction['status'], 'active.auction')

    def test_reschedule_auction(self):
        response = self.app.get('/recheck/' + self.auction_id)
        self.assertEqual(response.status, '200 OK')
        self.assertEqual(response.json, None)
        response = requests.get('{}/{}'.format(self.app.app.registry.full_url, self.auction_id))
        auction = response.json()['data']
        self.assertEqual(auction['status'], 'active.auction')
        if self.initial_lots:
            self.assertNotIn('auctionPeriod', auction)
            self.assertIn('auctionPeriod', auction['lots'][0])
            self.assertIn('shouldStartAfter', auction['lots'][0]['auctionPeriod'])
            self.assertNotIn('startDate', auction['lots'][0]['auctionPeriod'])
            self.assertGreater(auction['lots'][0]['auctionPeriod']['shouldStartAfter'], auction['lots'][0]['auctionPeriod'].get('startDate'))
        else:
            self.assertIn('auctionPeriod', auction)
            self.assertIn('shouldStartAfter', auction['auctionPeriod'])
            self.assertNotIn('startDate', auction['auctionPeriod'])
            self.assertGreater(auction['auctionPeriod']['shouldStartAfter'], auction['auctionPeriod'].get('startDate'))
        response = requests.get('{}/{}'.format(self.app.app.registry.full_url, self.auction_id))
        auction = response.json()['data']
        self.assertEqual(auction['status'], 'active.auction')
        response = self.app.get('/resync/' + self.auction_id)
        self.assertEqual(response.status, '200 OK')
        self.assertEqual(response.json, None)

        response = requests.get('{}/{}'.format(self.app.app.registry.full_url, self.auction_id))
        auction = response.json()['data']
        if self.initial_lots:
            self.assertIn('auctionPeriod', auction['lots'][0])
            auctionPeriod = auction['lots'][0]['auctionPeriod']['startDate']
            auction['lots'][0]['auctionPeriod']['startDate'] = (datetime.now(TZ) - timedelta(hours=1)).isoformat()
        else:
            self.assertIn('auctionPeriod', auction)
            auctionPeriod = auction['auctionPeriod']['startDate']
            auction['auctionPeriod']['startDate'] = (datetime.now(TZ) - timedelta(hours=1)).isoformat()
        update_json(self.api, 'auction', self.auction_id, {"data": auction})
        response = requests.patch('{}/{}'.format(self.app.app.registry.full_url, self.auction_id), {
            'data': {"id": "f547ece35436484e8656a2988fb52a44"}})
        self.assertEqual(response.status_code, 200)
        response = requests.get('{}/{}'.format(self.app.app.registry.full_url, self.auction_id))
        response.json = response.json()
        auction = response.json['data']
        self.assertEqual(auction['status'], 'active.auction')
        if self.initial_lots:
            self.assertNotIn('auctionPeriod', auction)
            self.assertIn('auctionPeriod', auction['lots'][0])
            self.assertIn('shouldStartAfter', auction['lots'][0]['auctionPeriod'])
            self.assertIn('startDate', auction['lots'][0]['auctionPeriod'])
            self.assertGreater(auction['lots'][0]['auctionPeriod']['shouldStartAfter'], auction['lots'][0]['auctionPeriod'].get('startDate'))
        else:
            self.assertIn('auctionPeriod', auction)
            self.assertIn('shouldStartAfter', auction['auctionPeriod'])
            self.assertIn('startDate', auction['auctionPeriod'])
            self.assertGreater(auction['auctionPeriod']['shouldStartAfter'], auction['auctionPeriod'].get('startDate'))
        response = self.app.get('/resync/' + self.auction_id)
        self.assertEqual(response.status, '200 OK')
        self.assertEqual(response.json, None)
        response = requests.get('{}/{}'.format(self.app.app.registry.full_url, self.auction_id))
        response.json = response.json()
        auction = response.json['data']
        if self.initial_lots:
            self.assertIn('auctionPeriod', auction['lots'][0])
            self.assertGreater(auction['lots'][0]['auctionPeriod']['startDate'], auctionPeriod)
        else:
            self.assertIn('auctionPeriod', auction)
            self.assertGreater(auction['auctionPeriod']['startDate'], auctionPeriod)


class AuctionLotTest3(AuctionTest3):
    initial_lots = test_lots


class AuctionTest4(AuctionTest3):
    sandbox = True


class AuctionLotTest4(AuctionTest4):
    initial_lots = test_lots


class AuctionPlanning(BaseWebTest):
    scheduler = False

    def test_auction_quick_planning(self):
        now = datetime.now(TZ)
        auctionPeriodstartDate = planning_auction(test_auction_data_test_quick, self.mapper, now, self.db, True)[0]
        self.assertTrue(now < auctionPeriodstartDate < now + timedelta(hours=1))

    def test_auction_quick_planning_insider(self):
        now = datetime.now(TZ)
        my_test_auction = deepcopy(test_auction_data_test_quick)
        my_test_auction['procurementMethodType'] = 'dgfInsider'
        auctionPeriodstartDate = planning_auction(
            my_test_auction, self.mapper, now, self.db, True
        )[0]
        self.assertTrue(
            now < auctionPeriodstartDate < now + timedelta(hours=1)
        )

    def test_auction_planning_overlow_insider(self):
        now = datetime.now(TZ)
        my_test_auction = deepcopy(test_auction_data_test_quick)
        my_test_auction['procurementMethodType'] = 'dgfInsider'
        res = planning_auction(my_test_auction, self.mapper, now, self.db)[0]
        startDate = res.date()
        count = 0
        while startDate == res.date():
            count += 1
            res = planning_auction(my_test_auction, self.mapper, now, self.db)[0]
        self.assertEqual(count, 15)

    def test_auction_planning_overlow(self):
        now = datetime.now(TZ)
        res = planning_auction(test_auction_data_test_quick, self.mapper, now, self.db)[0]
        startDate = res.date()
        count = 0
        while startDate == res.date():
            count += 1
            res = planning_auction(test_auction_data_test_quick, self.mapper, now, self.db)[0]
        self.assertEqual(count, 100)

    def test_auction_planning_free(self):
        now = datetime.now(TZ)
        test_auction_data_test_quick.pop("id")
        res = planning_auction(test_auction_data_test_quick, self.mapper, now, self.db)[0]
        startDate, startTime = res.date(), res.time()
        manager = get_manager_for_auction(test_auction_data, self.mapper)
        manager.free_slot(self.db, "plantest_{}".format(startDate.isoformat()), "", res)
        res = planning_auction(test_auction_data_test_quick, self.mapper, now, self.db)[0]
        self.assertEqual(res.time(), startTime)

    def test_auction_planning_buffer(self):
        some_date = datetime(2015, 9, 21, 6, 30)
        date = some_date.date()
        ndate = (some_date + timedelta(days=1)).date()
        res = planning_auction(test_auction_data_test_quick, self.mapper, some_date, self.db)[0]
        self.assertEqual(res.date(), date)
        some_date = some_date.replace(hour=10)
        res = planning_auction(test_auction_data_test_quick, self.mapper, some_date, self.db)[0]
        self.assertNotEqual(res.date(), date)
        self.assertEqual(res.date(), ndate)
        some_date = some_date.replace(hour=16)
        res = planning_auction(test_auction_data_test_quick, self.mapper, some_date, self.db)[0]
        self.assertNotEqual(res.date(), date)
        self.assertEqual(res.date(), ndate)


def suite():
    tests = unittest.TestSuite()
    tests.addTest(unittest.makeSuite(AuctionLotTest))
    tests.addTest(unittest.makeSuite(AuctionLotTest2))
    tests.addTest(unittest.makeSuite(AuctionLotTest3))
    tests.addTest(unittest.makeSuite(AuctionLotTest4))
    tests.addTest(unittest.makeSuite(AuctionPlanning))
    tests.addTest(unittest.makeSuite(AuctionTest))
    tests.addTest(unittest.makeSuite(AuctionTest2))
    tests.addTest(unittest.makeSuite(AuctionTest3))
    tests.addTest(unittest.makeSuite(AuctionTest4))
    tests.addTest(unittest.makeSuite(AuctionsTest))
    tests.addTest(unittest.makeSuite(SimpleTest))
    return tests


if __name__ == '__main__':
    unittest.main(defaultTest='suite', exit=False)
