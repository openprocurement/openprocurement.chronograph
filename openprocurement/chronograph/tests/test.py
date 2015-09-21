# -*- coding: utf-8 -*-
from datetime import datetime, timedelta
from copy import deepcopy
from iso8601 import parse_date
from time import sleep
from logging import getLogger

from openprocurement.chronograph import TZ
from openprocurement.chronograph.scheduler import planning_auction
from openprocurement.chronograph.tests.base import BaseWebTest, BaseTenderWebTest, test_tender_data


LOGGER = getLogger(__name__)
test_tender_data_quick = deepcopy(test_tender_data)
test_tender_data_quick.update({
    "enquiryPeriod": {
        'startDate': datetime.now(TZ).isoformat(),
        "endDate": datetime.now(TZ).isoformat()
    },
    'tenderPeriod': {
        'startDate': datetime.now(TZ).isoformat(),
        "endDate": datetime.now(TZ).isoformat()
    }
})
test_tender_data_test_quick = deepcopy(test_tender_data_quick)
test_tender_data_test_quick['mode'] = 'test'
test_bids = [
    {
        "tenderers": [
            test_tender_data["procuringEntity"]
        ],
        "value": {
            "amount": 469,
            "currency": "UAH",
            "valueAddedTaxIncluded": True
        }
    },
    {
        "tenderers": [
            test_tender_data["procuringEntity"]
        ],
        "value": {
            "amount": 479,
            "currency": "UAH",
            "valueAddedTaxIncluded": True
        }
    }
]


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


class TendersTest(BaseTenderWebTest):

    def test_list_jobs(self):
        response = self.app.get('/')
        self.assertEqual(response.status, '200 OK')
        self.assertIn('jobs', response.json)
        self.assertEqual(len(response.json['jobs']), 1)
        self.assertIn('resync_all', response.json['jobs'])
        response = self.app.get('/resync/' + self.tender_id)
        self.assertEqual(response.status, '200 OK')
        self.assertNotEqual(response.json, None)
        response = self.app.get('/')
        self.assertEqual(response.status, '200 OK')
        self.assertIn('jobs', response.json)
        self.assertEqual(len(response.json['jobs']), 2)
        self.assertIn(self.tender_id, response.json['jobs'])

    def test_resync_all(self):
        response = self.app.get('/resync_all')
        self.assertEqual(response.status, '200 OK')
        self.assertNotEqual(response.json, None)
        sleep(0.1)
        response = self.app.get('/')
        self.assertEqual(response.status, '200 OK')
        self.assertIn('jobs', response.json)
        self.assertEqual(len(response.json['jobs']), 2)
        self.assertIn(self.tender_id, response.json['jobs'])


class TenderTest(BaseTenderWebTest):
    scheduler = False

    def test_wait_for_enquiryPeriod(self):
        response = self.app.get('/resync/' + self.tender_id)
        self.assertEqual(response.status, '200 OK')
        self.assertNotEqual(response.json, None)
        response = self.api.get(self.app.app.registry.api_url + 'tenders/' + self.tender_id)
        tender = response.json['data']
        self.assertEqual(tender['status'], 'active.enquiries')

    def test_switch_to_tendering_enquiryPeriod(self):
        response = self.api.patch_json(self.app.app.registry.api_url + 'tenders/' + self.tender_id, {
            'data': {
                "enquiryPeriod": {
                    "endDate": datetime.now(TZ).isoformat()
                },
                'tenderPeriod': {
                    'startDate': None
                }
            }
        })
        response = self.app.get('/resync/' + self.tender_id)
        self.assertEqual(response.status, '200 OK')
        self.assertNotEqual(response.json, None)
        response = self.api.get(self.app.app.registry.api_url + 'tenders/' + self.tender_id)
        tender = response.json['data']
        self.assertEqual(tender['status'], 'active.tendering')

    def test_switch_to_tendering_tenderPeriod(self):
        response = self.api.patch_json(self.app.app.registry.api_url + 'tenders/' + self.tender_id, {
            'data': {
                "enquiryPeriod": {
                    "endDate": datetime.now(TZ).isoformat()
                },
                'tenderPeriod': {
                    'startDate': datetime.now(TZ).isoformat()
                }
            }
        })
        response = self.app.get('/resync/' + self.tender_id)
        self.assertEqual(response.status, '200 OK')
        self.assertNotEqual(response.json, None)
        response = self.api.get(self.app.app.registry.api_url + 'tenders/' + self.tender_id)
        tender = response.json['data']
        self.assertEqual(tender['status'], 'active.tendering')

    def test_wait_for_tenderPeriod(self):
        response = self.api.patch_json(self.app.app.registry.api_url + 'tenders/' + self.tender_id, {
            'data': {
                "enquiryPeriod": {
                    "endDate": datetime.now(TZ).isoformat()
                },
                'tenderPeriod': {
                    'startDate': (datetime.now(TZ) + timedelta(hours=1)).isoformat()
                }
            }
        })
        response = self.app.get('/resync/' + self.tender_id)
        self.assertEqual(response.status, '200 OK')
        self.assertNotEqual(response.json, None)
        response = self.api.get(self.app.app.registry.api_url + 'tenders/' + self.tender_id)
        tender = response.json['data']
        self.assertEqual(tender['status'], 'active.enquiries')

    def test_set_auctionPeriod_nextday(self):
        now = datetime.now(TZ)
        response = self.api.patch_json(self.app.app.registry.api_url + 'tenders/' + self.tender_id, {
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
        response = self.app.get('/resync/' + self.tender_id)
        self.assertEqual(response.status, '200 OK')
        self.assertNotEqual(response.json, None)
        response = self.api.get(self.app.app.registry.api_url + 'tenders/' + self.tender_id)
        tender = response.json['data']
        self.assertEqual(tender['status'], 'active.tendering')
        response = self.app.get('/resync/' + self.tender_id)
        self.assertEqual(response.status, '200 OK')
        self.assertNotEqual(response.json, None)
        response = self.api.get(self.app.app.registry.api_url + 'tenders/' + self.tender_id)
        tender = response.json['data']
        self.assertEqual(tender['status'], 'active.tendering')
        self.assertIn('auctionPeriod', tender)
        self.assertEqual(parse_date(tender['auctionPeriod']['startDate'], TZ).weekday(), 1)
        response = self.app.get('/resync/' + self.tender_id)
        self.assertEqual(response.status, '200 OK')
        self.assertNotEqual(response.json, None)
        self.app.app.registry.scheduler.start()
        response = self.app.get('/')
        self.assertEqual(response.status, '200 OK')
        self.assertIn('jobs', response.json)
        self.assertIn(self.tender_id, response.json['jobs'])
        self.assertEqual(response.json['jobs'][self.tender_id], tender['tenderPeriod']['endDate'])

    def test_set_auctionPeriod_skip_weekend(self):
        now = datetime.now(TZ)
        response = self.api.patch_json(self.app.app.registry.api_url + 'tenders/' + self.tender_id, {
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
        LOGGER.info('before call1')
        response = self.app.get('/resync/' + self.tender_id)
        LOGGER.info('after call1')
        self.assertEqual(response.status, '200 OK')
        self.assertNotEqual(response.json, None)
        response = self.api.get(self.app.app.registry.api_url + 'tenders/' + self.tender_id)
        tender = response.json['data']
        self.assertEqual(tender['status'], 'active.tendering')
        LOGGER.info('before call2')
        response = self.app.get('/resync/' + self.tender_id)
        LOGGER.info('after call2')
        self.assertEqual(response.status, '200 OK')
        self.assertNotEqual(response.json, None)
        response = self.api.get(self.app.app.registry.api_url + 'tenders/' + self.tender_id)
        tender = response.json['data']
        LOGGER.info('before error')
        self.assertEqual(tender['status'], 'active.tendering')
        self.assertIn('auctionPeriod', tender)
        self.assertEqual(parse_date(tender['auctionPeriod']['startDate'], TZ).weekday(), 0)

    def test_set_auctionPeriod_skip_holidays(self):
        now = datetime.now(TZ)
        today = now.date()
        for i in range(10):
            date = today + timedelta(days=i)
            self.app.post('/calendar/' + date.isoformat())
        calendar = self.app.get('/calendar').json
        response = self.api.patch_json(self.app.app.registry.api_url + 'tenders/' + self.tender_id, {
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
        response = self.app.get('/resync/' + self.tender_id)
        self.assertEqual(response.status, '200 OK')
        self.assertNotEqual(response.json, None)
        response = self.api.get(self.app.app.registry.api_url + 'tenders/' + self.tender_id)
        tender = response.json['data']
        self.assertEqual(tender['status'], 'active.tendering')
        response = self.app.get('/resync/' + self.tender_id)
        self.assertEqual(response.status, '200 OK')
        self.assertNotEqual(response.json, None)
        response = self.api.get(self.app.app.registry.api_url + 'tenders/' + self.tender_id)
        tender = response.json['data']
        self.assertEqual(tender['status'], 'active.tendering')
        self.assertIn('auctionPeriod', tender)
        auctionPeriodstart = parse_date(tender['auctionPeriod']['startDate'], TZ)
        self.assertNotIn(auctionPeriodstart.date().isoformat(), calendar)
        self.assertTrue(auctionPeriodstart.date() > date)

    def test_set_auctionPeriod_today(self):
        now = datetime.now(TZ)
        response = self.api.patch_json(self.app.app.registry.api_url + 'tenders/' + self.tender_id, {
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
        response = self.app.get('/resync/' + self.tender_id)
        self.assertEqual(response.status, '200 OK')
        self.assertNotEqual(response.json, None)
        response = self.api.get(self.app.app.registry.api_url + 'tenders/' + self.tender_id)
        tender = response.json['data']
        self.assertEqual(tender['status'], 'active.tendering')
        response = self.app.get('/resync/' + self.tender_id)
        self.assertEqual(response.status, '200 OK')
        self.assertNotEqual(response.json, None)
        response = self.api.get(self.app.app.registry.api_url + 'tenders/' + self.tender_id)
        tender = response.json['data']
        self.assertEqual(tender['status'], 'active.tendering')
        self.assertIn('auctionPeriod', tender)
        self.assertEqual(parse_date(tender['auctionPeriod']['startDate'], TZ).weekday(), 0)

    def test_switch_to_unsuccessful(self):
        response = self.api.patch_json(self.app.app.registry.api_url + 'tenders/' + self.tender_id, {
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
        response = self.app.get('/resync/' + self.tender_id)
        self.assertEqual(response.status, '200 OK')
        self.assertNotEqual(response.json, None)
        response = self.api.get(self.app.app.registry.api_url + 'tenders/' + self.tender_id)
        tender = response.json['data']
        self.assertEqual(tender['status'], 'active.tendering')
        response = self.app.get('/resync/' + self.tender_id)
        self.assertEqual(response.status, '200 OK')
        self.assertEqual(response.json, None)
        response = self.api.get(self.app.app.registry.api_url + 'tenders/' + self.tender_id)
        tender = response.json['data']
        self.assertEqual(tender['status'], 'unsuccessful')


class TenderTest2(BaseTenderWebTest):
    scheduler = False
    initial_data = test_tender_data_quick
    initial_bids = test_bids[:1]

    def test_switch_to_qualification(self):
        response = self.app.get('/resync/' + self.tender_id)
        self.assertEqual(response.status, '200 OK')
        self.assertNotEqual(response.json, None)
        response = self.api.get(self.app.app.registry.api_url + 'tenders/' + self.tender_id)
        tender = response.json['data']
        self.assertEqual(tender['status'], 'active.qualification')

    def test_switch_to_unsuccessful(self):
        response = self.app.get('/resync/' + self.tender_id)
        self.assertEqual(response.status, '200 OK')
        self.assertNotEqual(response.json, None)
        response = self.api.get(self.app.app.registry.api_url + 'tenders/' + self.tender_id)
        tender = response.json['data']
        self.assertEqual(tender['status'], 'active.qualification')
        self.assertIn('awards', tender)
        award = tender['awards'][0]
        response = self.api.patch_json(self.app.app.registry.api_url + 'tenders/' + self.tender_id + '/awards/' + award['id'], {"data": {"status": "unsuccessful"}})
        self.assertEqual(response.status, '200 OK')
        self.assertEqual(response.content_type, 'application/json')
        response = self.app.get('/resync/' + self.tender_id)
        self.assertEqual(response.status, '200 OK')
        self.assertNotEqual(response.json, None)
        response = self.api.get(self.app.app.registry.api_url + 'tenders/' + self.tender_id)
        tender = response.json['data']
        self.assertEqual(tender['status'], 'active.awarded')
        tender = self.api_db.get(self.tender_id)
        tender['awards'][0]['complaintPeriod']['endDate'] = datetime.now(TZ).isoformat()
        self.api_db.save(tender)
        response = self.app.get('/resync/' + self.tender_id)
        self.assertEqual(response.status, '200 OK')
        self.assertEqual(response.json, None)
        response = self.api.get(self.app.app.registry.api_url + 'tenders/' + self.tender_id)
        tender = response.json['data']
        self.assertEqual(tender['status'], 'unsuccessful')


class TenderTest3(BaseTenderWebTest):
    scheduler = False
    initial_data = test_tender_data_quick
    initial_bids = test_bids

    def test_switch_to_auction(self):
        response = self.app.get('/resync/' + self.tender_id)
        self.assertEqual(response.status, '200 OK')
        self.assertNotEqual(response.json, None)
        response = self.api.get(self.app.app.registry.api_url + 'tenders/' + self.tender_id)
        tender = response.json['data']
        self.assertEqual(tender['status'], 'active.auction')

    def test_reschedule_auction(self):
        response = self.app.get('/resync/' + self.tender_id)
        self.assertEqual(response.status, '200 OK')
        self.assertNotEqual(response.json, None)
        response = self.api.get(self.app.app.registry.api_url + 'tenders/' + self.tender_id)
        tender = response.json['data']
        self.assertEqual(tender['status'], 'active.auction')
        self.assertNotIn('auctionPeriod', tender)
        response = self.app.get('/resync/' + self.tender_id)
        self.assertEqual(response.status, '200 OK')
        self.assertNotEqual(response.json, None)
        tender = self.api_db.get(self.tender_id)
        self.assertIn('auctionPeriod', tender)
        tender['auctionPeriod']['startDate'] = (datetime.now(TZ) - timedelta(hours=1)).isoformat()
        self.api_db.save(tender)
        response = self.app.get('/resync/' + self.tender_id)
        self.assertEqual(response.status, '200 OK')
        self.assertNotEqual(response.json, None)


class TenderTest4(TenderTest3):
    sandbox = True


class TenderPlanning(BaseWebTest):

    def test_auction_quick_planning(self):
        now = datetime.now(TZ)
        res = planning_auction(test_tender_data_test_quick, now, self.db, True)
        auctionPeriodstartDate = parse_date(res['startDate'], TZ)
        self.assertTrue(now < auctionPeriodstartDate < now + timedelta(hours=1))

    def test_auction_planning_overlow(self):
        now = datetime.now(TZ)
        res = planning_auction(test_tender_data_test_quick, now, self.db)
        startDate = res['startDate'][:10]
        count = 0
        while startDate == res['startDate'][:10]:
            count += 1
            res = planning_auction(test_tender_data_test_quick, now, self.db)
        self.assertEqual(count, 100)
