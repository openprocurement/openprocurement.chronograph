import os
import unittest
from ConfigParser import ConfigParser
from couchdb import Server
from datetime import datetime
from openprocurement.chronograph.scheduler import check_inner_auction
from openprocurement.chronograph.tests.data import plantest
from openprocurement.chronograph.design import sync_design


class SchedulerTest(unittest.TestCase):

    def setUp(self):
        conf = ConfigParser()
        path_to_config = '{}/openprocurement/chronograph/tests/' \
            'chronograph.ini'.format(os.getcwd())
        if os.path.isfile(path_to_config):
            conf.read(path_to_config)
            settings = {k: v for k, v in conf.items('app:main')}
            self.server = Server(settings['couchdb.url'])
            self.settings = settings
            self.db = self.server[settings['couchdb.db_name']] if \
                settings['couchdb.db_name'] in self.server else \
                self.server.create(settings['couchdb.db_name'])
            sync_design(self.db)
            plantest['_id'] = 'plantest_{}'.format(
                datetime.now().date().isoformat())
            plantest_from_db = self.db.get(plantest['_id'], {})
            plantest_from_db.update(plantest)
            self.db.save(plantest_from_db)

    def tearDown(self):
        if hasattr(self, 'db'):
            del self.server[self.settings['couchdb.db_name']]

    def test_check_inner_auction(self):
        insider_auction_id = '01fa8a7dc4b8eac3b5820747efc6fe36'
        classic_auction_with_lots = 'da8a28ed2bdf73ee1d373e4cadfed4c5'
        classic_auction_without_lots = 'e51508cddc2c490005eaecb73c006b72'
        lots_ids = ['1c2fb1e496b317b2b87e197e2332da77',
                    'b10f9f7f26157ae2f349be8dc2106d6e']
        today = datetime.now().date().isoformat()
        auction = {
            'id': insider_auction_id,
            'procurementMethodType': 'dgfInsider',
            'auctionPeriod': {
                'startDate': datetime.now().isoformat()
            }
        }

        plantest = self.db.get('plantest_{}'.format(today))

        # Test insider
        self.assertEqual(len(plantest.get('dutch_streams', [])), 15)
        self.assertIn(insider_auction_id, plantest.get('dutch_streams'))
        check_inner_auction(self.db, auction)
        plantest = self.db.get('plantest_{}'.format(today))
        self.assertEqual(len(plantest.get('dutch_streams', [])), 6)
        self.assertNotIn(insider_auction_id, plantest.get('dutch_streams'))

        # Test classic with lots
        auction['procurementMethodType'] = 'classic'
        auction['id'] = classic_auction_with_lots
        auction['lots'] = [
            {
                'id': lots_ids[0],
                'auctionPeriod': {'startDate': datetime.now().isoformat()}
            },
            {
                'id': lots_ids[1],
                'auctionPeriod': {'startDate': datetime.now().isoformat()}
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
        check_inner_auction(self.db, auction)
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
        check_inner_auction(self.db, auction)
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
    suite = unittest.TestSuite()
    suite.addTest(unittest.makeSuite(SchedulerTest))
    return suite


if __name__ == '__main__':
    unittest.main(defaultTest='suite', exit=False)
