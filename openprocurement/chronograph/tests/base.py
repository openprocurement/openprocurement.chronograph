# -*- coding: utf-8 -*-
import unittest
import webtest
import os
import requests.api
from datetime import datetime, timedelta
from requests.models import Response
from requests.structures import CaseInsensitiveDict
from requests.utils import get_encoding_from_headers
from openprocurement.chronograph.scheduler import SESSION
from openprocurement.api.utils import VERSION
try:
    from openprocurement.api.tests.base import test_tender_data
except ImportError:
    now = datetime.now()
    test_tender_data = {
        "title": u"футляри до державних нагород",
        "procuringEntity": {
            "name": u"Державне управління справами",
            "identifier": {
                "scheme": u"UA-EDR",
                "id": u"00037256",
                "uri": u"http://www.dus.gov.ua/"
            },
            "address": {
                "countryName": u"Україна",
                "postalCode": u"01220",
                "region": u"м. Київ",
                "locality": u"м. Київ",
                "streetAddress": u"вул. Банкова, 11, корпус 1"
            },
            "contactPoint": {
                "name": u"Державне управління справами",
                "telephone": u"0440000000"
            }
        },
        "value": {
            "amount": 500,
            "currency": u"UAH"
        },
        "minimalStep": {
            "amount": 35,
            "currency": u"UAH"
        },
        "items": [
            {
                "description": u"футляри до державних нагород",
                "classification": {
                    "scheme": u"CPV",
                    "id": u"44617100-9",
                    "description": u"Cartons"
                },
                "additionalClassifications": [
                    {
                        "scheme": u"ДКПП",
                        "id": u"17.21.1",
                        "description": u"папір і картон гофровані, паперова й картонна тара"
                    }
                ],
                "unit": {
                    "name": u"item",
                    "code": u"44617100-9"
                },
                "quantity": 5
            }
        ],
        "enquiryPeriod": {
            "endDate": (now + timedelta(days=7)).isoformat()
        },
        "tenderPeriod": {
            "endDate": (now + timedelta(days=14)).isoformat()
        }
    }


class BaseWebTest(unittest.TestCase):

    """Base Web Test to test openprocurement.api.

    It setups the database before each test and delete it after.
    """
    scheduler = True

    def setUp(self):
        self.api = api = webtest.TestApp("config:tests.ini", relative_to=os.path.dirname(__file__))
        self.api.authorization = ('Basic', ('token', ''))
        self.api_db = self.api.app.registry.db
        app = None

        def request(method, url, **kwargs):
            if 'data' in kwargs:
                kwargs['params'] = kwargs.pop('data')
            elif 'params' in kwargs and kwargs['params'] is None:
                kwargs.pop('params')
            auth = None
            if 'auth' in kwargs:
                auth = kwargs.pop('auth')
            for i in ['auth', 'allow_redirects', 'stream']:
                if i in kwargs:
                    kwargs.pop(i)
            try:
                if app.app.registry.api_url in url:
                    if auth:
                        authorization = api.authorization
                        api.authorization = ('Basic', auth)
                    resp = api._gen_request(method.upper(), url, expect_errors=True, **kwargs)
                    if auth:
                        api.authorization = authorization
                else:
                    resp = app._gen_request(method.upper(), url, expect_errors=True, **kwargs)
            except:
                response = Response()
                response.status_code = 404
            else:
                response = Response()
                response.status_code = resp.status_int
                response.headers = CaseInsensitiveDict(getattr(resp, 'headers', {}))
                response.encoding = get_encoding_from_headers(response.headers)
                response.raw = resp
                response._content = resp.body
                response.reason = resp.status
                if isinstance(url, bytes):
                    response.url = url.decode('utf-8')
                else:
                    response.url = url
                response.request = resp.request
            return response

        self._request = requests.api.request
        requests.api.request = request
        self._srequest = SESSION.request
        SESSION.request = request

        self.app = app = webtest.TestApp("config:chronograph.ini", relative_to=os.path.dirname(__file__))
        self.app.app.registry.api_url = self.app.app.registry.api_url.replace('0.12', VERSION)
        self.couchdb_server = self.app.app.registry.couchdb_server
        self.db = self.app.app.registry.db
        if not self.scheduler:
            self.app.app.registry.scheduler.shutdown()

    def tearDown(self):
        requests.api.request = self._request
        SESSION.request = self._srequest
        del self.couchdb_server[self.api_db.name]
        del self.couchdb_server[self.db.name]


class BaseTenderWebTest(BaseWebTest):
    initial_data = test_tender_data
    initial_bids = None
    initial_lots = None
    sandbox = False

    def setUp(self):
        super(BaseTenderWebTest, self).setUp()
        if self.sandbox:
            os.environ['SANDBOX_MODE'] = "True"
        # Create tender
        self.api.authorization = ('Basic', ('token', ''))
        response = self.api.post_json('{}tenders'.format(self.app.app.registry.api_url), {'data': self.initial_data})
        tender = response.json['data']
        self.tender_id = tender['id']
        if self.initial_lots:
            lots = []
            for i in self.initial_lots:
                response = self.api.post_json('{}tenders/{}/lots'.format(self.app.app.registry.api_url, self.tender_id), {'data': i})
                self.assertEqual(response.status, '201 Created')
                lots.append(response.json['data'])
            self.initial_lots = lots
            response = self.api.patch_json('{}tenders/{}'.format(self.app.app.registry.api_url, self.tender_id), {"data": {
                "items": [
                    {
                        'relatedLot': lots[i % len(lots)]['id']
                    }
                    for i in xrange(len(tender['items']))
                ]
            }})
            self.assertEqual(response.status, '200 OK')
        if self.initial_bids:
            self.api.authorization = ('Basic', ('chronograph', ''))
            now = datetime.now()
            data = self.api_db.get(self.tender_id)
            data.update({
                "enquiryPeriod": {
                    "startDate": now.isoformat(),
                    "endDate": now.isoformat()
                },
                "tenderPeriod": {
                    "startDate": now.isoformat(),
                    "endDate": (now + timedelta(days=1)).isoformat()
                }
            })
            self.api_db.save(data)
            for _ in range(100):
                response = self.api.patch_json('{}tenders/{}'.format(self.app.app.registry.api_url, self.tender_id), {
                    'data': {
                        'id': self.tender_id
                    }
                })
                if response.json['data']['status'] == 'active.tendering':
                    break
            self.api.authorization = ('Basic', ('token', ''))
            bids = []
            for i in self.initial_bids:
                if self.initial_lots:
                    i = i.copy()
                    value = i.pop('value')
                    i['lotValues'] = [
                        {
                            'value': value,
                            'relatedLot': lot['id'],
                        }
                        for lot in self.initial_lots
                    ]
                response = self.api.post_json(self.app.app.registry.api_url + 'tenders/' + self.tender_id + '/bids', {'data': i})
                bids.append(response.json['data'])
            self.initial_bids = bids
            data = self.api_db.get(self.tender_id)
            data.update({
                'status': 'active.tendering',
                "enquiryPeriod": tender["enquiryPeriod"],
                "tenderPeriod": tender["tenderPeriod"]
            })
            self.api_db.save(data)
            self.api.authorization = ('Basic', ('token', ''))

    def tearDown(self):
        if self.sandbox:
            os.environ.pop('SANDBOX_MODE')
        #del self.api_db[self.tender_id]
        super(BaseTenderWebTest, self).tearDown()
