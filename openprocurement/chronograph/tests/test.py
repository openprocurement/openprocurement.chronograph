# -*- coding: utf-8 -*-
from datetime import datetime, timedelta
from copy import deepcopy
from iso8601 import parse_date

from openprocurement.api.tests.base import test_tender_data
from openprocurement.chronograph import TZ
from openprocurement.chronograph.tests.base import BaseWebTest, BaseTenderWebTest


test_tender_data_quick = deepcopy(test_tender_data)
test_tender_data_quick.update({
    "enquiryPeriod": {
        'startDate': datetime.now().isoformat(),
        "endDate": datetime.now().isoformat()
    },
    'tenderPeriod': {
        'startDate': datetime.now().isoformat(),
        "endDate": datetime.now().isoformat()
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


class TenderTest(BaseTenderWebTest):

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
        response = self.app.get('/')
        self.assertEqual(response.status, '200 OK')
        self.assertIn('jobs', response.json)
        self.assertEqual(len(response.json['jobs']), 2)
        self.assertIn(self.tender_id, response.json['jobs'])

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
                    "endDate": datetime.now().isoformat()
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
                    "endDate": datetime.now().isoformat()
                },
                'tenderPeriod': {
                    'startDate': datetime.now().isoformat()
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
                    "endDate": datetime.now().isoformat()
                },
                'tenderPeriod': {
                    'startDate': (datetime.now() + timedelta(hours=1)).isoformat()
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
        now = datetime.now()
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
        response = self.app.get('/')
        self.assertEqual(response.status, '200 OK')
        self.assertIn('jobs', response.json)
        self.assertIn(self.tender_id, response.json['jobs'])
        self.assertEqual(response.json['jobs'][self.tender_id], tender['tenderPeriod']['endDate'])

    def test_set_auctionPeriod_skip_weekend(self):
        now = datetime.now()
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

    def test_set_auctionPeriod_today(self):
        now = datetime.now()
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
                    "endDate": datetime.now().isoformat()
                },
                'tenderPeriod': {
                    'startDate': datetime.now().isoformat(),
                    "endDate": datetime.now().isoformat()
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
        tender['awards'][0]['complaintPeriod']['endDate'] = datetime.now().isoformat()
        self.api_db.save(tender)
        response = self.app.get('/resync/' + self.tender_id)
        self.assertEqual(response.status, '200 OK')
        self.assertEqual(response.json, None)
        response = self.api.get(self.app.app.registry.api_url + 'tenders/' + self.tender_id)
        tender = response.json['data']
        self.assertEqual(tender['status'], 'unsuccessful')


class TenderTest3(BaseTenderWebTest):
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
        tender['auctionPeriod']['startDate'] = (datetime.now() - timedelta(hours=1)).isoformat()
        self.api_db.save(tender)
        response = self.app.get('/resync/' + self.tender_id)
        self.assertEqual(response.status, '200 OK')
        self.assertNotEqual(response.json, None)


class TenderTest4(TenderTest3):
    sandbox = True
