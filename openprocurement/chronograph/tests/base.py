# -*- coding: utf-8 -*-
import unittest
import webtest
import os
from openprocurement.chronograph import scheduler
from openprocurement.api.tests.base import test_tender_data
import requests.api
from requests.models import Response
from requests.structures import CaseInsensitiveDict
from requests.utils import get_encoding_from_headers


class PrefixedRequestClass(webtest.app.TestRequest):

    @classmethod
    def blank(cls, path, *args, **kwargs):
        path = '/api/%s%s' % (VERSION, path)
        return webtest.app.TestRequest.blank(path, *args, **kwargs)


class BaseWebTest(unittest.TestCase):

    """Base Web Test to test openprocurement.api.

    It setups the database before each test and delete it after.
    """

    def setUp(self):
        self.api = api = webtest.TestApp("config:tests.ini", relative_to=os.path.dirname(__file__))
        #self.app.RequestClass = PrefixedRequestClass
        self.api.authorization = ('Basic', ('token', ''))
        #self.couchdb_server = self.api.app.registry.couchdb_server
        self.api_db = self.api.app.registry.db

        def request(method, url, **kwargs):
            if 'data' in kwargs:
                kwargs['params'] = kwargs.pop('data')
            elif 'params' in kwargs and kwargs['params'] is None:
                kwargs.pop('params')
            auth = None
            if 'auth' in kwargs:
                auth = kwargs.pop('auth')
            for i in ['auth', 'allow_redirects']:
                if i in kwargs:
                    kwargs.pop(i)
            if app.app.registry.api_url in url:
                if auth:
                    authorization = api.authorization
                    api.authorization = ('Basic', auth)
                resp = api._gen_request(method.upper(), url, expect_errors=True, **kwargs)
                if auth:
                    api.authorization = authorization
            else:
                resp = app._gen_request(method.upper(), url, expect_errors=True, **kwargs)
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

        self._get_request = scheduler.get_request
        #scheduler.get_request = get_request
        self._push = scheduler.push
        #scheduler.push = push
        self.app = app = webtest.TestApp("config:chronograph.ini", relative_to=os.path.dirname(__file__))
        #self.app.RequestClass = PrefixedRequestClass
        #self.app.authorization = ('Basic', ('token', ''))
        self.couchdb_server = self.app.app.registry.couchdb_server
        self.db = self.app.app.registry.db

    def tearDown(self):
        scheduler.get_request = self._get_request
        scheduler.push = self._push
        requests.api.request = self._request
        del self.couchdb_server[self.api_db.name]
        del self.couchdb_server[self.db.name]


class BaseTenderWebTest(BaseWebTest):
    initial_data = test_tender_data
    initial_bids = None
    sandbox = False

    def setUp(self):
        super(BaseTenderWebTest, self).setUp()
        if self.sandbox:
            os.environ['SANDBOX_MODE'] = "True"
        # Create tender
        self.api.authorization = ('Basic', ('token', ''))
        response = self.api.post_json(self.app.app.registry.api_url + 'tenders', {'data': self.initial_data})
        tender = response.json['data']
        self.tender_id = tender['id']
        if self.initial_bids:
            response = self.api.patch_json(self.app.app.registry.api_url + 'tenders/' + self.tender_id, {
                'data': {
                    'status': 'active.tendering'
                }
            })
            bids = []
            for i in self.initial_bids:
                response = self.api.post_json(self.app.app.registry.api_url + 'tenders/' + self.tender_id + '/bids', {'data': i})
                bids.append(response.json['data'])
            self.initial_bids = bids

    def tearDown(self):
        if self.sandbox:
            os.environ.pop('SANDBOX_MODE')
        del self.api_db[self.tender_id]
        super(BaseTenderWebTest, self).tearDown()
