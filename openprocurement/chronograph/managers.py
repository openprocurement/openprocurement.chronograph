# -*- coding: utf-8 -*-
from copy import deepcopy

from couchdb import ResourceConflict
from datetime import timedelta, datetime
from iso8601 import parse_date

from openprocurement.chronograph.constants import (
    WORKING_DAY_START,
    WORKING_DAY_END,
    TEXAS_WORKING_DAY_START,
    INSIDER_WORKING_DAY_START,
    DEFAULT_STREAMS_DOC,
    STREAMS_ID,
    INSIDER_WORKING_DAY_DURATION,
    TEXAS_WORKING_DAY_DURATION
)
from openprocurement.chronograph.utils import TZ, find_free_slot


class BaseAuctionsManager(object):
    working_day_start = None
    streams_key = None

    def get_date(self, db, mode, date):
        """

        Get hour of auction start and stream in which auction will run for
        passed date.

        :param db: chronograph database with plan docs
        :type db: couchdb.Database
        :param mode: value from auction procedure, indicates mode of auction, used in plan doc id
        :type mode: str
        :param date: preplanned date for current auction
        :type date: datetime.date

        :returns : (time of auction start, stream for auction, plan document)
        :rtype: (datetime.time, int, couchdb.client.Document)
        """
        plan_id = 'plan{}_{}'.format(mode, date.isoformat())
        plan = db.get(plan_id, {'_id': plan_id})
        plan_date_end, stream = self._get_hours_and_stream(plan)
        plan_date = parse_date(date.isoformat() + 'T' + plan_date_end, None)
        plan_date = plan_date.astimezone(TZ) if plan_date.tzinfo else TZ.localize(plan_date)
        return plan_date.time(), stream, plan

    def get_streams(self, db, streams_id=STREAMS_ID):
        """

        Get allowed amount of streams for auction of particular type per day.

        :param db: chronograph database
        :type db: couchdb.Database
        :param streams_id: id of document with defined stream amounts
        :type streams_id: str

        :return: amount of streams for auction per day
        :rtype: int
        """

        streams = db.get(streams_id, deepcopy(DEFAULT_STREAMS_DOC))
        return streams.get(self.streams_key, DEFAULT_STREAMS_DOC[self.streams_key])

    def _get_hours_and_stream(self, plan):
        """
        Return time of auction start and first available stream from plan doc

        :param plan: document for planned auctions
        :type plan: couchdb.client.Document

        :return: (time of auction start, first available stream)
        :rtype: (str, int)
        """
        raise NotImplementedError

    def set_end_of_auction(self, *args, **kwargs):
        """
        Try to find end of auction for passed date, time and plan doc if such
        action is possible and return it's value for further auction planning
        """
        raise NotImplementedError

    def set_date(self, *args, **kwargs):
        """
        Actually plan auction for particular date, time, stream and slot and
        save it to chronograph database.
        """
        raise NotImplementedError

    def free_slot(self, *args, **kwargs):
        """
        Remove particular auction from stream slot in particular plan document.
        """
        raise NotImplementedError


class ClassicAuctionsManager(BaseAuctionsManager):
    working_day_start = WORKING_DAY_START
    working_day_end = WORKING_DAY_END
    streams_key = 'streams'

    def _get_hours_and_stream(self, plan):
        plan_date_end = plan.get('time', self.working_day_start.isoformat())
        stream = plan.get(self.streams_key, 1)
        return plan_date_end, stream

    def set_date(self, db, plan, auction_id, end_time,
                 cur_stream, start_time, new_slot=True):
        if new_slot:
            plan['time'] = end_time.isoformat()
            plan[self.streams_key] = cur_stream
        stream_id = 'stream_{}'.format(cur_stream)
        stream = plan.get(stream_id, {})
        stream[start_time.isoformat()] = auction_id
        plan[stream_id] = stream
        db.save(plan)

    def free_slot(self, db, plan_id, auction_id, plan_time):
        slot = plan_time.time().isoformat()
        done = False
        while not done:
            try:
                plan = db.get(plan_id)
                streams = plan[self.streams_key]
                for cur_stream in range(1, streams + 1):
                    stream_id = 'stream_{}'.format(cur_stream)
                    if plan[stream_id].get(slot) == auction_id:
                        plan[stream_id][slot] = None
                db.save(plan)
                done = True
            except ResourceConflict:
                done = False
            except:
                done = True

    def set_end_of_auction(self, stream, streams, nextDate, dayStart, plan):
        freeSlot = find_free_slot(plan)
        if freeSlot:
            startDate, stream = freeSlot
            start, end, dayStart, new_slot = startDate, startDate, startDate.time(), False
            return start, end, dayStart, stream, new_slot
        if dayStart >= self.working_day_end and stream < streams:
            stream += 1
            dayStart = self.working_day_start

        start = TZ.localize(datetime.combine(nextDate, dayStart))
        end = start + timedelta(minutes=30)

        # end = calc_auction_end_time(auction.get('numberOfBids', len(auction.get('bids', []))), start)

        # TODO: redundant check, which was used with previous end calculation logic:
        # if dayStart == self.working_day_start and end > TZ.localize(
        #     datetime.combine(nextDate, self.working_day_end)
        # ) and stream <= streams:
        #     return start, end, dayStart, stream, True

        if end <= TZ.localize(datetime.combine(nextDate, self.working_day_end)) and stream <= streams:
            return start, end, dayStart, stream, True


class NonClassicAuctionsManager(BaseAuctionsManager):
    working_day_start = None
    working_day_duration = None
    streams_key = None

    def _get_hours_and_stream(self, plan):
        plan_date_end = self.working_day_start.isoformat()
        stream = len(plan.get(self.streams_key, []))
        return plan_date_end, stream

    def set_date(self, db, plan, auction_id, *args, **kwargs):
        streams = plan.get(self.streams_key, [])
        streams.append(auction_id)
        plan[self.streams_key] = streams
        db.save(plan)

    def free_slot(self, db, plan_id, auction_id, *args, **kwargs):
        done = False
        while not done:
            try:
                plan = db.get(plan_id)
                slots = plan.get(self.streams_key, [])
                pops = []
                for i in xrange(0, len(slots)):
                    if slots[i] == auction_id:
                        pops.append(i)
                pops.sort(reverse=True)
                for p in pops:
                    slots.pop(p)
                plan[self.streams_key] = slots
                db.save(plan)
                done = True
            except ResourceConflict:
                done = False
            except:
                done = True

    def set_end_of_auction(self, stream, streams, nextDate, dayStart, *args, **kwargs):
        if stream < streams:
            start = TZ.localize(datetime.combine(nextDate, dayStart))
            end = start + self.working_day_duration
            return start, end, dayStart, stream, False


class TexasAuctionsManager(NonClassicAuctionsManager):
    working_day_start = TEXAS_WORKING_DAY_START
    working_day_duration = TEXAS_WORKING_DAY_DURATION
    streams_key = 'texas_streams'


class InsiderAuctionsManager(NonClassicAuctionsManager):
    working_day_start = INSIDER_WORKING_DAY_START
    working_day_duration = INSIDER_WORKING_DAY_DURATION
    streams_key = 'dutch_streams'


MANAGERS_MAPPING = {
    'texas': TexasAuctionsManager,
    'insider': InsiderAuctionsManager,
    'english': ClassicAuctionsManager
}
