# -*- coding: utf-8 -*-
from datetime import timedelta, time

CALENDAR_ID = 'calendar'
STREAMS_ID = 'streams'
WORKING_DAY_START = time(11, 0)
INSIDER_WORKING_DAY_START = time(9, 30)
TEXAS_WORKING_DAY_START = time(10, 0)
WORKING_DAY_END = time(16, 0)
INSIDER_WORKING_DAY_DURATION = timedelta(minutes=480)
TEXAS_WORKING_DAY_DURATION = timedelta(hours=7)  # Does not affect anything
ROUNDING = timedelta(minutes=29)
MIN_PAUSE = timedelta(minutes=3)
BIDDER_TIME = timedelta(minutes=6)
SERVICE_TIME = timedelta(minutes=9)
STAND_STILL_TIME = timedelta(days=1)
SMOOTHING_MIN = 10
SMOOTHING_REMIN = 60
# value should be greater than SMOOTHING_MIN and SMOOTHING_REMIN
SMOOTHING_MAX = 300
NOT_CLASSIC_AUCTIONS = ['dgfInsider', 'sellout.insider']
STREAMS_KEYS = ['streams', 'dutch_streams', 'texas_streams']
DEFAULT_STREAMS_DOC = {
    '_id': STREAMS_ID,
    'streams': 10,
    'dutch_streams': 15,
    'texas_streams': 20
}

AUCTIONS = [
    {
        'type': 'insider',
        'pmts': ['dgfInsider', 'sellout.insider']
    },
    {
        'type': 'texas',
        'pmts': ['landLease']
    },
    {
        'type': 'english'
    }
]
