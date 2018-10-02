# -*- coding: utf-8 -*-
from __future__ import print_function

import os
import sys
import unittest
from datetime import timedelta
from json import dumps, loads

import requests.api
import webtest
from bottle import Bottle
from gevent.pywsgi import WSGIServer
from requests.models import Response
from requests.structures import CaseInsensitiveDict
from requests.utils import get_encoding_from_headers

from openprocurement.chronograph.scheduler import SESSION
from openprocurement.chronograph.tests.data import test_auction_data
from openprocurement.chronograph.tests.test_server import (
    API_VERSION as VERSION, resource_filter, PORT, setup_routing
 )
from openprocurement.chronograph.tests.utils import (
    now, update_periods, update_json
)
from openprocurement.chronograph.utils import get_full_url

data = {"data": test_auction_data}


class BaseWebTest(unittest.TestCase):
    """Base Web Test to test openprocurement.api.

    It setups the database before each test and delete it after.
    """
    scheduler = True

    def setUp(self):

        self.api = Bottle()
        self.api.config['auction_{}'.format(data['data']['id'])] = dumps(data)
        self.api.config['feed_changes'] = 0
        self.api.router.add_filter('resource_filter', resource_filter)
        setup_routing(self.api)
        setup_routing(self.api, routes=[
            "auction_patch", "auction", "auctions", "auction_subpage_item_patch"
        ])
        self.server = WSGIServer(('localhost', PORT), self.api, log=None)
        try:
            self.server.start()
        except Exception as error:
            print(sys.exc_info()[0], sys.exc_info()[1], sys.exc_info()[2],
                  file=sys.stderr)
            raise error

        def request(method, url, **kwargs):
            if 'data' in kwargs and app.app.registry.api_url not in url:
                kwargs['params'] = kwargs.pop('data')
            elif 'params' in kwargs and kwargs['params'] is None:
                kwargs.pop('params')
            for i in ['auth', 'allow_redirects', 'stream']:
                if i in kwargs:
                    kwargs.pop(i)
            try:
                if app.app.registry.api_url in url:

                    if kwargs.get('params'):
                        if loads(kwargs['params']).get('data'):
                            kwargs['data'] = kwargs.pop('params')
                    if kwargs.get('data') and not kwargs.get('headers'):
                        kwargs['json'] = kwargs.pop('data')

                    resp = self._request(method.upper(), url, **kwargs)
                    if 'errors' in resp.json():
                        resp.status_code = 404  # mocked api app can return only 404 location errors
                else:
                    resp = app._gen_request(method.upper(), url, expect_errors=True, **kwargs)
            except:
                response = Response()
                response.status_code = 404
            else:
                if isinstance(resp, Response):
                    response = resp
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
        self.app.app.registry.full_url = get_full_url(self.app.app.registry)
        self.couchdb_server = self.app.app.registry.couchdb_server
        self.db = self.app.app.registry.db
        self.mapper = self.app.app.registry.manager_mapper
        if not self.scheduler:
            self.app.app.registry.scheduler.shutdown()

    def tearDown(self):
        self.api.config['feed_changes'] = 0
        requests.api.request = self._request
        SESSION.request = self._srequest
        self.server.stop()
        try:
            del self.couchdb_server[self.db.name]
        except:
            pass


class BaseAuctionWebTest(BaseWebTest):
    auction_id = test_auction_data["id"]
    initial_bids = None
    initial_lots = None
    sandbox = False
    quick = False

    def setUp(self):
        super(BaseAuctionWebTest, self).setUp()
        if self.sandbox:
            os.environ['SANDBOX_MODE'] = "True"
        self.auction = update_periods(self.api, 'auction', self.auction_id, self.quick)
        if self.initial_lots:

            lots = []
            for lot in self.initial_lots:
                lot['date'] = now.isoformat()
                lots.append(lot)
            self.initial_lots = lots
            response = requests.get('{}/{}'.format(self.app.app.registry.full_url, self.auction_id))
            auction = response.json()['data']
            auction['lots'] = lots
            update_json(self.api, 'auction', self.auction_id, {"data": auction})
            response = requests.patch('{}/{}'.format(self.app.app.registry.full_url, self.auction_id),
                                      {"data": {"id": "f547ece35436484e8656a2988fb52a44"}})
            self.assertEqual(response.status_code, 200)

            auction = response.json()['data']
            for i in xrange(len(auction['items'])):
                auction['items'][i].update({'relatedLot': lots[i % len(lots)]['id']})
            response = requests.patch('{}/{}'.format(self.app.app.registry.full_url, self.auction_id), {"data": auction})
            self.assertEqual(response.status_code, 200)

        if self.initial_bids:
            response = requests.get('{}/{}'.format(self.app.app.registry.full_url, self.auction_id))
            self.assertEqual(response.status_code, 200)
            response.json = response.json()
            auction = response.json['data']

            response = requests.patch('{}/{}'.format(self.app.app.registry.full_url, self.auction_id), {
                'data': {
                    "enquiryPeriod": {
                        "startDate": now.isoformat(),
                        "endDate": now.isoformat()
                    },
                    "tenderPeriod": {
                        "startDate": now.isoformat(),
                        "endDate": (now + timedelta(days=1)).isoformat()
                    }
                }
            })

            self.assertEqual(response.status_code, 200)

            bids = []
            for i in self.initial_bids:
                i['date'] = now.isoformat()
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

                bids.append(i)
            self.initial_bids = bids
            response = requests.patch('{}/{}'.format(self.app.app.registry.full_url, self.auction_id),
                                      {"data": {"bids": bids}})
            self.assertEqual(response.status_code, 200)
            auction_with_bids = response.json()['data']

            auction_with_bids.update({
                'status': 'active.tendering',
                "enquiryPeriod": auction["enquiryPeriod"],
                "tenderPeriod": auction["tenderPeriod"]
            })
            update_json(self.api, 'auction', self.auction_id, {"data": auction_with_bids})

    def tearDown(self):
        if self.sandbox:
            os.environ.pop('SANDBOX_MODE')
        super(BaseAuctionWebTest, self).tearDown()
        update_json(self.api, 'auction', self.auction_id, self.auction)
