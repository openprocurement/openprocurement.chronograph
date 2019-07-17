import os
import unittest
from ConfigParser import ConfigParser
from couchdb import Server
from datetime import datetime
from iso8601 import parse_date

from openprocurement.chronograph import MANAGERS_MAPPING
from openprocurement.chronograph.scheduler import check_inner_auction, TZ
from openprocurement.chronograph.tests.data import plantest
from openprocurement.chronograph.design import sync_design

dir_path = os.path.dirname(os.path.realpath(__file__))


class SchedulerTest(unittest.TestCase):

    def setUp(self):
        conf = ConfigParser()
        path_to_config = os.path.join(dir_path, 'chronograph.ini')
        if os.path.isfile(path_to_config):
            conf.read(path_to_config)
            settings = {k: v for k, v in conf.items('app:main')}
            couchdb_url = os.environ.get('COUCHDB_URL', settings.get('couchdb.url'))
            self.db_name = os.environ.get('DB_NAME', settings['couchdb.db_name'])
            self.server = Server(couchdb_url)
            self.settings = settings
            self.db = self.server[self.db_name] if self.db_name in self.server else self.server.create(self.db_name)
            sync_design(self.db)
            plantest['_id'] = 'plantest_{}'.format(
                datetime.now().date().isoformat())
            plantest_from_db = self.db.get(plantest['_id'], {})
            plantest_from_db.update(plantest)
            self.db.save(plantest_from_db)

    def tearDown(self):
        if hasattr(self, 'db'):
            del self.server[self.db_name]

    def test_check_inner_auction(self):
        insider_auction_id = '01fa8a7dc4b8eac3b5820747efc6fe36'
        texas_auction_id = 'dc3d950743304d05adaa1cd5b0475075'
        classic_auction_with_lots = 'da8a28ed2bdf73ee1d373e4cadfed4c5'
        classic_auction_without_lots = 'e51508cddc2c490005eaecb73c006b72'
        lots_ids = ['1c2fb1e496b317b2b87e197e2332da77',
                    'b10f9f7f26157ae2f349be8dc2106d6e']

        today = datetime.now().date().isoformat()
        time = '12:15:00'  # actually, can be any time between 12:00:00 and 12:30:00 due to existing asserts
        raw_time = ''.join([today, 'T', time])

        # datetime.datetime object prepared in the way scheduler actually does it:
        test_time = TZ.localize(parse_date(raw_time, None)).isoformat()

        auction = {
            'id': insider_auction_id,
            'procurementMethodType': 'dgfInsider',
            'auctionPeriod': {
                'startDate': test_time
            }
        }
        mapper = {
            'pmts': {
                'dgfInsider': MANAGERS_MAPPING['insider'](),
                'landLease': MANAGERS_MAPPING['texas']()
            },
            'types': {'english': MANAGERS_MAPPING['english']()}
        }

        plantest = self.db.get('plantest_{}'.format(today))

        # Test insider
        self.assertEqual(len(plantest.get('dutch_streams', [])), 15)
        self.assertIn(insider_auction_id, plantest.get('dutch_streams'))

        check_inner_auction(self.db, auction, mapper)
        plantest = self.db.get('plantest_{}'.format(today))
        self.assertEqual(len(plantest.get('dutch_streams', [])), 6)
        self.assertNotIn(insider_auction_id, plantest.get('dutch_streams'))

        # Test texas
        auction['id'] = texas_auction_id
        auction['procurementMethodType'] = 'landLease'

        self.assertEqual(len(plantest.get('texas_streams', [])), 20)
        self.assertIn(texas_auction_id, plantest.get('texas_streams'))

        check_inner_auction(self.db, auction, mapper)
        plantest = self.db.get('plantest_{}'.format(today))
        self.assertEqual(len(plantest.get('texas_streams', [])), 15)
        self.assertNotIn(texas_auction_id, plantest.get('texas_streams'))

        # Test classic with lots
        auction['procurementMethodType'] = 'classic'
        auction['id'] = classic_auction_with_lots
        auction['lots'] = [
            {
                'id': lots_ids[0],
                'auctionPeriod': {'startDate': test_time}
            },
            {
                'id': lots_ids[1],
                'auctionPeriod': {'startDate': test_time}
            }
        ]
        self.assertEqual(len(plantest.get('stream_1')), 10)
        self.assertEqual(len(plantest.get('stream_2')), 10)
        stream_1_none_count = len(
            [v for k, v in plantest.get('stream_1').items() if v is None])
        stream_2_none_count = len(
            [v for k, v in plantest.get('stream_2').items() if v is None])
        self.assertEqual(stream_1_none_count, 0)
        self.assertEqual(stream_2_none_count, 0)
        check_inner_auction(self.db, auction, mapper)
        plantest = self.db.get('plantest_{}'.format(today))
        self.assertEqual(len(plantest.get('stream_1')), 10)
        self.assertEqual(len(plantest.get('stream_2')), 10)
        stream_1_none_count = len(
            [v for k, v in plantest.get('stream_1').items() if v is None])
        stream_2_none_count = len(
            [v for k, v in plantest.get('stream_2').items() if v is None])
        self.assertEqual(stream_1_none_count, 3)
        self.assertEqual(stream_2_none_count, 3)
        self.assertNotIn(classic_auction_with_lots,
                         plantest.get('stream_1', {}).values())
        self.assertNotIn(classic_auction_with_lots,
                         plantest.get('stream_2', {}).values())

        # Test classic without lots
        del auction['lots']
        auction['id'] = classic_auction_without_lots
        check_inner_auction(self.db, auction, mapper)
        plantest = self.db.get('plantest_{}'.format(today))
        self.assertEqual(len(plantest.get('stream_1')), 10)
        self.assertEqual(len(plantest.get('stream_2')), 10)
        stream_1_none_count = len(
            [v for k, v in plantest.get('stream_1').items() if v is None])
        stream_2_none_count = len(
            [v for k, v in plantest.get('stream_2').items() if v is None])
        self.assertEqual(stream_1_none_count, 7)
        self.assertEqual(stream_2_none_count, 6)
        self.assertNotIn(classic_auction_without_lots,
                         plantest.get('stream_1', {}).values())
        self.assertNotIn(classic_auction_without_lots,
                         plantest.get('stream_2', {}).values())


def suite():
    tests = unittest.TestSuite()
    tests.addTest(unittest.makeSuite(SchedulerTest))
    return tests


if __name__ == '__main__':
    unittest.main(defaultTest='suite', exit=False)
