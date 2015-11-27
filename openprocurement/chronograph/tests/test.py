# -*- coding: utf-8 -*-
import unittest
from datetime import datetime, timedelta
from copy import deepcopy
from iso8601 import parse_date
from time import sleep
from logging import getLogger

from openprocurement.chronograph import TZ
from openprocurement.chronograph.scheduler import planning_auction
from openprocurement.chronograph.tests.base import BaseWebTest, BaseAuctionWebTest, test_auction_data

try:
    from openprocurement.api.tests.base import test_bids
except ImportError:
    test_bids = [
        {
            "tenderers": [
                test_auction_data["procuringEntity"]
            ],
            "value": {
                "amount": 469,
                "currency": "UAH",
                "valueAddedTaxIncluded": True
            }
        },
        {
            "tenderers": [
                test_auction_data["procuringEntity"]
            ],
            "value": {
                "amount": 479,
                "currency": "UAH",
                "valueAddedTaxIncluded": True
            }
        }
    ]

try:
    from openprocurement.api.tests.base import test_lots
except ImportError:
    test_lots = [
        {
            'title': 'lot title',
            'description': 'lot description',
            'value': test_auction_data['value'],
            'minimalStep': test_auction_data['minimalStep'],
        }
    ]


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
        response = self.app.get('/streams')
        self.assertEqual(response.status, '200 OK')
        self.assertEqual(response.json, 10)
        response = self.app.post('/streams', {'streams': 20})
        self.assertEqual(response.status, '200 OK')
        self.assertEqual(response.json, True)
        response = self.app.get('/streams')
        self.assertEqual(response.status, '200 OK')
        self.assertEqual(response.json, 20)
        response = self.app.post('/streams', {'streams': -20})
        self.assertEqual(response.status, '200 OK')
        self.assertEqual(response.json, False)
        response = self.app.post('/streams', {'streams': 10})
        self.assertEqual(response.status, '200 OK')
        self.assertEqual(response.json, True)


class AuctionsTest(BaseAuctionWebTest):

    def test_list_jobs(self):
        response = self.app.get('/')
        self.assertEqual(response.status, '200 OK')
        self.assertIn('jobs', response.json)
        self.assertEqual(len(response.json['jobs']), 1)
        self.assertIn('resync_all', response.json['jobs'])
        response = self.app.get('/resync/' + self.auction_id)
        self.assertEqual(response.status, '200 OK')
        self.assertNotEqual(response.json, None)
        response = self.app.get('/')
        self.assertEqual(response.status, '200 OK')
        self.assertIn('jobs', response.json)
        self.assertEqual(len(response.json['jobs']), 2)
        self.assertIn(self.auction_id, response.json['jobs'])

    def test_resync_all(self):
        response = self.app.get('/resync_all')
        self.assertEqual(response.status, '200 OK')
        self.assertNotEqual(response.json, None)
        sleep(0.1)
        response = self.app.get('/')
        self.assertEqual(response.status, '200 OK')
        self.assertIn('jobs', response.json)
        self.assertEqual(len(response.json['jobs']), 2)
        self.assertIn(self.auction_id, response.json['jobs'])


class AuctionTest(BaseAuctionWebTest):
    scheduler = False

    def test_wait_for_enquiryPeriod(self):
        response = self.app.get('/resync/' + self.auction_id)
        self.assertEqual(response.status, '200 OK')
        self.assertNotEqual(response.json, None)
        response = self.api.get(self.app.app.registry.api_url + 'auctions/' + self.auction_id)
        auction = response.json['data']
        self.assertEqual(auction['status'], 'active.enquiries')

    def test_switch_to_auctioning_enquiryPeriod(self):
        response = self.api.patch_json(self.app.app.registry.api_url + 'auctions/' + self.auction_id, {
            'data': {
                "enquiryPeriod": {
                    "endDate": datetime.now(TZ).isoformat()
                },
                'tenderPeriod': {
                    'startDate': None
                }
            }
        })
        response = self.app.get('/resync/' + self.auction_id)
        self.assertEqual(response.status, '200 OK')
        self.assertNotEqual(response.json, None)
        response = self.api.get(self.app.app.registry.api_url + 'auctions/' + self.auction_id)
        auction = response.json['data']
        self.assertEqual(auction['status'], 'active.tendering')

    def test_switch_to_auctioning_tenderPeriod(self):
        response = self.api.patch_json(self.app.app.registry.api_url + 'auctions/' + self.auction_id, {
            'data': {
                "enquiryPeriod": {
                    "endDate": datetime.now(TZ).isoformat()
                },
                'tenderPeriod': {
                    'startDate': datetime.now(TZ).isoformat()
                }
            }
        })
        response = self.app.get('/resync/' + self.auction_id)
        self.assertEqual(response.status, '200 OK')
        self.assertNotEqual(response.json, None)
        response = self.api.get(self.app.app.registry.api_url + 'auctions/' + self.auction_id)
        auction = response.json['data']
        self.assertEqual(auction['status'], 'active.tendering')

    def test_wait_for_tenderPeriod(self):
        response = self.api.patch_json(self.app.app.registry.api_url + 'auctions/' + self.auction_id, {
            'data': {
                "enquiryPeriod": {
                    "endDate": datetime.now(TZ).isoformat()
                },
                'tenderPeriod': {
                    'startDate': (datetime.now(TZ) + timedelta(hours=1)).isoformat()
                }
            }
        })
        response = self.app.get('/resync/' + self.auction_id)
        self.assertEqual(response.status, '200 OK')
        self.assertNotEqual(response.json, None)
        response = self.api.get(self.app.app.registry.api_url + 'auctions/' + self.auction_id)
        auction = response.json['data']
        self.assertEqual(auction['status'], 'active.enquiries')

    def test_set_auctionPeriod_nextday(self):
        now = datetime.now(TZ)
        response = self.api.patch_json(self.app.app.registry.api_url + 'auctions/' + self.auction_id, {
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
        response = self.app.get('/resync/' + self.auction_id)
        self.assertEqual(response.status, '200 OK')
        self.assertNotEqual(response.json, None)
        response = self.api.get(self.app.app.registry.api_url + 'auctions/' + self.auction_id)
        auction = response.json['data']
        self.assertEqual(auction['status'], 'active.tendering')
        response = self.app.get('/resync/' + self.auction_id)
        self.assertEqual(response.status, '200 OK')
        self.assertNotEqual(response.json, None)
        response = self.api.get(self.app.app.registry.api_url + 'auctions/' + self.auction_id)
        auction = response.json['data']
        self.assertEqual(auction['status'], 'active.tendering')
        if self.initial_lots:
            self.assertIn('auctionPeriod', auction['lots'][0])
            self.assertEqual(parse_date(auction['lots'][0]['auctionPeriod']['startDate'], TZ).weekday(), 1)
        else:
            self.assertIn('auctionPeriod', auction)
            self.assertEqual(parse_date(auction['auctionPeriod']['startDate'], TZ).weekday(), 1)
        response = self.app.get('/resync/' + self.auction_id)
        self.assertEqual(response.status, '200 OK')
        self.assertNotEqual(response.json, None)
        self.app.app.registry.scheduler.start()
        response = self.app.get('/')
        self.assertEqual(response.status, '200 OK')
        self.assertIn('jobs', response.json)
        self.assertIn(self.auction_id, response.json['jobs'])
        self.assertEqual(parse_date(response.json['jobs'][self.auction_id]).utctimetuple(), parse_date(auction['tenderPeriod']['endDate']).utctimetuple())

    def test_set_auctionPeriod_skip_weekend(self):
        now = datetime.now(TZ)
        response = self.api.patch_json(self.app.app.registry.api_url + 'auctions/' + self.auction_id, {
            'data': {
                "enquiryPeriod": {
                    "endDate": now.isoformat()
                },
                'tenderPeriod': {
                    'startDate': now.isoformat(),
                    'endDate': (now + timedelta(days=5 - now.weekday())).isoformat()
                }
            }
        })
        response = self.app.get('/resync/' + self.auction_id)
        self.assertEqual(response.status, '200 OK')
        self.assertNotEqual(response.json, None)
        response = self.api.get(self.app.app.registry.api_url + 'auctions/' + self.auction_id)
        auction = response.json['data']
        self.assertEqual(auction['status'], 'active.tendering')
        response = self.app.get('/resync/' + self.auction_id)
        self.assertEqual(response.status, '200 OK')
        self.assertNotEqual(response.json, None)
        response = self.api.get(self.app.app.registry.api_url + 'auctions/' + self.auction_id)
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
        response = self.api.patch_json(self.app.app.registry.api_url + 'auctions/' + self.auction_id, {
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
        response = self.app.get('/resync/' + self.auction_id)
        self.assertEqual(response.status, '200 OK')
        self.assertNotEqual(response.json, None)
        response = self.api.get(self.app.app.registry.api_url + 'auctions/' + self.auction_id)
        auction = response.json['data']
        self.assertEqual(auction['status'], 'active.tendering')
        response = self.app.get('/resync/' + self.auction_id)
        self.assertEqual(response.status, '200 OK')
        self.assertNotEqual(response.json, None)
        response = self.api.get(self.app.app.registry.api_url + 'auctions/' + self.auction_id)
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
        response = self.api.patch_json(self.app.app.registry.api_url + 'auctions/' + self.auction_id, {
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
        response = self.app.get('/resync/' + self.auction_id)
        self.assertEqual(response.status, '200 OK')
        self.assertNotEqual(response.json, None)
        response = self.api.get(self.app.app.registry.api_url + 'auctions/' + self.auction_id)
        auction = response.json['data']
        self.assertEqual(auction['status'], 'active.tendering')
        response = self.app.get('/resync/' + self.auction_id)
        self.assertEqual(response.status, '200 OK')
        self.assertNotEqual(response.json, None)
        response = self.api.get(self.app.app.registry.api_url + 'auctions/' + self.auction_id)
        auction = response.json['data']
        self.assertEqual(auction['status'], 'active.tendering')
        if self.initial_lots:
            self.assertIn('auctionPeriod', auction['lots'][0])
            self.assertEqual(parse_date(auction['lots'][0]['auctionPeriod']['startDate'], TZ).weekday(), 0)
        else:
            self.assertIn('auctionPeriod', auction)
            self.assertEqual(parse_date(auction['auctionPeriod']['startDate'], TZ).weekday(), 0)

    def test_switch_to_unsuccessful(self):
        response = self.api.patch_json(self.app.app.registry.api_url + 'auctions/' + self.auction_id, {
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
        response = self.app.get('/resync/' + self.auction_id)
        self.assertEqual(response.status, '200 OK')
        self.assertNotEqual(response.json, None)
        response = self.api.get(self.app.app.registry.api_url + 'auctions/' + self.auction_id)
        auction = response.json['data']
        self.assertEqual(auction['status'], 'active.tendering')
        response = self.app.get('/resync/' + self.auction_id)
        self.assertEqual(response.status, '200 OK')
        self.assertEqual(response.json, None)
        response = self.api.get(self.app.app.registry.api_url + 'auctions/' + self.auction_id)
        auction = response.json['data']
        self.assertEqual(auction['status'], 'unsuccessful')


class AuctionLotTest(AuctionTest):
    initial_lots = test_lots


class AuctionTest2(BaseAuctionWebTest):
    scheduler = False
    initial_data = test_auction_data_quick
    initial_bids = test_bids[:1]

    def test_switch_to_qualification(self):
        response = self.app.get('/resync/' + self.auction_id)
        self.assertEqual(response.status, '200 OK')
        self.assertNotEqual(response.json, None)
        response = self.api.get(self.app.app.registry.api_url + 'auctions/' + self.auction_id)
        auction = response.json['data']
        self.assertEqual(auction['status'], 'active.qualification')

    def test_switch_to_unsuccessful(self):
        response = self.app.get('/resync/' + self.auction_id)
        self.assertEqual(response.status, '200 OK')
        self.assertNotEqual(response.json, None)
        response = self.api.get(self.app.app.registry.api_url + 'auctions/' + self.auction_id)
        auction = response.json['data']
        self.assertEqual(auction['status'], 'active.qualification')
        self.assertIn('awards', auction)
        award = auction['awards'][0]
        response = self.api.patch_json(self.app.app.registry.api_url + 'auctions/' + self.auction_id + '/awards/' + award['id'], {"data": {"status": "unsuccessful"}})
        self.assertEqual(response.status, '200 OK')
        self.assertEqual(response.content_type, 'application/json')
        response = self.app.get('/resync/' + self.auction_id)
        self.assertEqual(response.status, '200 OK')
        self.assertNotEqual(response.json, None)
        response = self.api.get(self.app.app.registry.api_url + 'auctions/' + self.auction_id)
        auction = response.json['data']
        self.assertEqual(auction['status'], 'active.awarded')
        auction = self.api_db.get(self.auction_id)
        auction['awards'][0]['complaintPeriod']['endDate'] = datetime.now(TZ).isoformat()
        self.api_db.save(auction)
        response = self.app.get('/resync/' + self.auction_id)
        self.assertEqual(response.status, '200 OK')
        self.assertEqual(response.json, None)
        response = self.api.get(self.app.app.registry.api_url + 'auctions/' + self.auction_id)
        auction = response.json['data']
        self.assertEqual(auction['status'], 'unsuccessful')


class AuctionLotTest2(AuctionTest2):
    initial_lots = test_lots


class AuctionTest3(BaseAuctionWebTest):
    scheduler = False
    initial_data = test_auction_data_quick
    initial_bids = test_bids

    def test_switch_to_auction(self):
        response = self.app.get('/resync/' + self.auction_id)
        self.assertEqual(response.status, '200 OK')
        self.assertNotEqual(response.json, None)
        response = self.api.get(self.app.app.registry.api_url + 'auctions/' + self.auction_id)
        auction = response.json['data']
        self.assertEqual(auction['status'], 'active.auction')

    def test_reschedule_auction(self):
        response = self.app.get('/resync/' + self.auction_id)
        self.assertEqual(response.status, '200 OK')
        self.assertNotEqual(response.json, None)
        response = self.api.get(self.app.app.registry.api_url + 'auctions/' + self.auction_id)
        auction = response.json['data']
        self.assertEqual(auction['status'], 'active.auction')
        self.assertNotIn('auctionPeriod', auction)
        response = self.app.get('/resync/' + self.auction_id)
        self.assertEqual(response.status, '200 OK')
        self.assertNotEqual(response.json, None)
        auction = self.api_db.get(self.auction_id)
        if self.initial_lots:
            self.assertIn('auctionPeriod', auction['lots'][0])
            auctionPeriod = auction['lots'][0]['auctionPeriod']['startDate']
            auction['lots'][0]['auctionPeriod']['startDate'] = (datetime.now(TZ) - timedelta(hours=1)).isoformat()
        else:
            self.assertIn('auctionPeriod', auction)
            auctionPeriod = auction['auctionPeriod']['startDate']
            auction['auctionPeriod']['startDate'] = (datetime.now(TZ) - timedelta(hours=1)).isoformat()
        self.api_db.save(auction)
        response = self.app.get('/resync/' + self.auction_id)
        self.assertEqual(response.status, '200 OK')
        self.assertNotEqual(response.json, None)
        auction = self.api_db.get(self.auction_id)
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

    def test_auction_quick_planning(self):
        now = datetime.now(TZ)
        auctionPeriodstartDate = planning_auction(test_auction_data_test_quick, now, self.db, True)[0]
        self.assertTrue(now < auctionPeriodstartDate < now + timedelta(hours=1))

    def test_auction_planning_overlow(self):
        now = datetime.now(TZ)
        res = planning_auction(test_auction_data_test_quick, now, self.db)[0]
        startDate = res.date()
        count = 0
        while startDate == res.date():
            count += 1
            res = planning_auction(test_auction_data_test_quick, now, self.db)[0]
        self.assertEqual(count, 100)

    def test_auction_planning_buffer(self):
        some_date = datetime(2015, 9, 21, 6, 30)
        date = some_date.date()
        ndate = (some_date + timedelta(days=1)).date()
        res = planning_auction(test_auction_data_test_quick, some_date, self.db)[0]
        self.assertEqual(res.date(), date)
        some_date = some_date.replace(hour=10)
        res = planning_auction(test_auction_data_test_quick, some_date, self.db)[0]
        self.assertNotEqual(res.date(), date)
        self.assertEqual(res.date(), ndate)
        some_date = some_date.replace(hour=16)
        res = planning_auction(test_auction_data_test_quick, some_date, self.db)[0]
        self.assertNotEqual(res.date(), date)
        self.assertEqual(res.date(), ndate)


def suite():
    suite = unittest.TestSuite()
    suite.addTest(unittest.makeSuite(SimpleTest))
    suite.addTest(unittest.makeSuite(AuctionLotTest))
    suite.addTest(unittest.makeSuite(AuctionLotTest2))
    suite.addTest(unittest.makeSuite(AuctionLotTest3))
    suite.addTest(unittest.makeSuite(AuctionLotTest4))
    suite.addTest(unittest.makeSuite(AuctionPlanning))
    suite.addTest(unittest.makeSuite(AuctionTest))
    suite.addTest(unittest.makeSuite(AuctionTest2))
    suite.addTest(unittest.makeSuite(AuctionTest3))
    suite.addTest(unittest.makeSuite(AuctionTest4))
    suite.addTest(unittest.makeSuite(AuctionsTest))
    return suite


if __name__ == '__main__':
    unittest.main(defaultTest='suite')
