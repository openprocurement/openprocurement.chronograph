from copy import deepcopy
from datetime import timedelta, datetime, time
from json import dumps, loads

import dateutil.parser
from munch import munchify

from openprocurement.chronograph import TZ

now = datetime.now(TZ)

BIDDER_TIME = timedelta(minutes=3 * 3)
SERVICE_TIME = timedelta(minutes=5 + 3 + 3)
AUCTION_STAND_STILL_TIME = timedelta(minutes=15)


def check_status(auction):

    if auction.status == 'active.enquiries' \
            and not auction.tenderPeriod.startDate \
            and auction.enquiryPeriod.endDate <= datetime.now(TZ).isoformat():
        auction = set_tendering_period(auction)

    elif auction.status == 'active.enquiries' \
            and auction.tenderPeriod.startDate \
            and auction.tenderPeriod.startDate <= datetime.now(TZ).isoformat():
        auction = set_tendering_period(auction)

    elif not auction.get('lots') and auction.status == 'active.tendering' \
            and auction.tenderPeriod.endDate <= datetime.now(TZ).isoformat():
        auction.status = 'active.auction'

        auction = remove_draft_bids(auction)
        auction = check_bids(auction)

    elif auction.get('lots') and auction.status == 'active.tendering' and auction.tenderPeriod.get('endDate', '') and auction.tenderPeriod.endDate <= datetime.now(TZ).isoformat():
        auction.status = 'active.auction'
        remove_draft_bids(auction)
        check_bids(auction)
        for i in auction.lots:
            if len(i.get('bids', '')) < 2 and i.get('auctionPeriod'):
                if i.auctionPeriod.get('startDate'):
                    i.auctionPeriod.pop('startDate')

    elif not auction.get('lots', '') and auction.status == 'active.awarded':
        standStillEnds = [
            a.complaintPeriod.get('endDate')
            for a in auction.awards
        ]
        if not standStillEnds:
            return auction
        standStillEnd = max(standStillEnds)
        if standStillEnd <= datetime.now(TZ).isoformat():
            auction = check_auction_status(auction)

    elif auction.get('lots') and auction.status in ['active.qualification', 'active.awarded']:
        if any([i['status'] in ['claim', 'answered', 'pending'] and not i.get('relatedLot', '') for i in auction.get('complaints', '')]):
            return
        for lot in auction.lots:
            if lot['status'] != 'active':
                continue
            lot_awards = [i for i in auction.awards if i.lotID == lot.id]
            standStillEnds = [
                a.complaintPeriod.get('endDate')
                for a in lot_awards
            ]
            if not standStillEnds:
                continue
            standStillEnd = max(standStillEnds)
            if standStillEnd <= datetime.now(TZ).isoformat():
                auction = check_auction_status(auction)

    checks = []

    if auction.status == 'active.enquiries' and auction.tenderPeriod.get('startDate'):
        checks.append(auction.tenderPeriod.startDate)
    elif auction.status == 'active.enquiries' and auction.enquiryPeriod.get('endDate'):
        checks.append(auction.enquiryPeriod.endDate)
    elif auction.status == 'active.tendering' and auction.tenderPeriod.get('endDate'):
        checks.append(auction.tenderPeriod.endDate)
    elif not auction.get('lots') and auction.status == 'active.auction' and auction.get('auctionPeriod') and auction.auctionPeriod.get('startDate') and not auction.get('auctionPeriod.endDate'):
        if datetime.now(TZ).isoformat() < auction.auctionPeriod.startDate:
            checks.append(auction.auctionPeriod.startDate)
        elif datetime.now(TZ).isoformat() > auction.auctionPeriod.startDate:
            start_after = calc_auction_end_time(len(auction.get('bids', '')), dateutil.parser.parse(auction.auctionPeriod.startDate))
            auction['auctionPeriod']['shouldStartAfter'] = start_after.isoformat()
        elif datetime.now(TZ) < calc_auction_end_time(len(auction.get('bids', '')), dateutil.parser.parse(auction.auctionPeriod.get('startDate'))):
            checks.append(calc_auction_end_time(len(auction.get('bids', '')), auction.auctionPeriod.get('startDate')))
    elif auction.get('lots') and auction.status == 'active.auction':
        auction_lots = deepcopy(auction.lots)
        for lot in auction.lots:

            if lot.status != 'active' or not lot.get('auctionPeriod') or not lot.auctionPeriod.get('startDate') or lot.auctionPeriod.get('endDate'):
                continue

            for lot in auction.lots:
                lot['bids'] = []
                for bid in auction.get('bids', ''):
                    if bid.get('lotValues'):
                        for value in bid['lotValues']:
                            if value['relatedLot'] == lot['id']:
                                lot['bids'].append(bid)

            if datetime.now(TZ).isoformat() < lot.auctionPeriod.startDate:
                checks.append(lot.auctionPeriod.startDate)

            elif datetime.now(TZ) < calc_auction_end_time(len(lot['bids']), dateutil.parser.parse(lot.auctionPeriod.startDate)).astimezone(TZ):
                checks.append(calc_auction_end_time(len(lot['bids']), dateutil.parser.parse(lot.auctionPeriod.startDate).astimezone(TZ)))
        auction.lots = auction_lots
    if checks:

        auction.next_check = min(checks)

    if auction.status == 'active.auction' and auction.get('next_check'):
        auction.pop('next_check')

    return auction


def check_auction_status(auction):
    stand_still_ends = [
        a.complaintPeriod.get('endDate', '')
        for a in auction.get('awards', '')
    ]
    stand_still_end = max(stand_still_ends) if stand_still_ends else now
    stand_still_time_expired = stand_still_end < now.isoformat()
    if auction.get('awards', ''):
        last_award_status = auction.awards[-1].status
    else:
        last_award_status = ''
    if not stand_still_time_expired and last_award_status == 'unsuccessful':
        auction.status = 'unsuccessful'
        auction.pop('next_check')
    return auction


def calc_auction_end_time(bids, start):
    return start + bids * BIDDER_TIME + SERVICE_TIME + AUCTION_STAND_STILL_TIME


def set_tendering_period(auction):
    auction.status = 'active.tendering'
    if not auction.get('lots'):
        auction['auctionPeriod'] = {}
    else:
        for i, lot in enumerate(auction.lots):
            lot['auctionPeriod'] = {}

    if auction.tenderPeriod.get('endDate'):
        start_after = auction.tenderPeriod.endDate
        if not auction.get('lots'):
            auction['auctionPeriod']['shouldStartAfter'] = rounding_shouldStartAfter(
                dateutil.parser.parse(start_after)).isoformat()
        else:
            for i, lot in enumerate(auction.lots):
                lot['auctionPeriod']['shouldStartAfter'] = rounding_shouldStartAfter(
                    dateutil.parser.parse(start_after)).isoformat()
    return auction


def rounding_shouldStartAfter(start_after):
    midnight = datetime.combine(start_after.date(), time(0, tzinfo=start_after.tzinfo))
    if start_after > midnight:
        start_after = midnight + timedelta(1)
    return start_after


def remove_draft_bids(auction):
    if auction.get('bids'):
        if [bid for bid in auction.get('bids') if getattr(bid, "status", "active") == "draft"]:
            auction.bids = [bid for bid in auction.bids if getattr(bid, "status", "active") != "draft"]
    return auction


def check_bids(auction):
    if auction.get('lots'):
        auction_lots = deepcopy(auction.lots)
        for lot in auction.lots:
            lot['bids'] = []
            for bid in auction.get('bids', ''):
                if bid.get('lotValues'):
                    for value in bid['lotValues']:
                        if value['relatedLot'] == lot['id']:
                            lot['bids'].append(bid)
        [i.auctionPeriod.pop('startDate') for i in auction.lots if len(i.get('bids', '')) < 2 and i.get('auctionPeriod', '') and i.auctionPeriod.get('startDate')]
        [setattr(i, 'status', 'unsuccessful') for i in auction.lots if len(i.get('bids', '')) == 0 and i.status == 'active']
        unsuccessful_lots = [lot for lot in auction.lots if lot.status == 'unsuccessful']
        if unsuccessful_lots:
            if auction.get('next_check'):
                auction.pop('next_check')
        if len(unsuccessful_lots) == len(auction.lots):
            auction.status = "unsuccessful"
        elif max([len(i.get('bids', '')) for i in auction.lots if i.status == 'active']) < 2:
            auction.status = 'active.qualification'
            auction['awards'] = [{
                "id": "1234567890abcdef1234567890abcdef",
                "value": auction.bids[0].lotValues[0].value,
                "suppliers": auction.bids[0].tenderers,
                "status": "pending",
                "bid_id": auction.bids[0].id,
                "date": now.isoformat(),
                "lotID": auction.bids[0].lotValues[0].relatedLot,
                "complaintPeriod": {
                    "startDate": now.isoformat()
                }
            }]
        auction.lots = auction_lots

    else:
        if not auction.get('bids'):
            auction.status = 'unsuccessful'
            auction.pop('next_check')

        if len(auction.get('bids', '')) == 1:
            auction.status = 'active.qualification'
            auction['awards'] = [{
                "id": "1234567890abcdef1234567890abcdef",
                "value": auction.bids[0].value,
                "suppliers": auction.bids[0].tenderers,
                "status": "pending",
                "bid_id": auction.bids[0].id,
                "date": now.isoformat(),
                "complaintPeriod": {
                    "startDate": now.isoformat()
                }
            }]
            auction.pop('next_check')

    return auction


def update_periods(app, resource_name, resource_id, quick=False):
    resource = resource_partition(app, resource_id, resource_name)
    if not resource:
        return location_error(resource_name)
    data = deepcopy(resource['data'])

    data["date"] = now.isoformat()
    data["dateModified"] = now.isoformat()
    data["next_check"] = (now + timedelta(days=7)).isoformat()
    if quick:
        data["enquiryPeriod"]["endDate"] = now.isoformat()
        data["enquiryPeriod"]["startDate"] = now.isoformat()
        data["tenderPeriod"]["startDate"] = now.isoformat()
        data["tenderPeriod"]["endDate"] = now.isoformat()
    else:
        data["enquiryPeriod"]["endDate"] = (now + timedelta(days=7)).isoformat()
        data["enquiryPeriod"]["startDate"] = now.isoformat()
        data["tenderPeriod"]["startDate"] = (now + timedelta(days=7)).isoformat()
        data["tenderPeriod"]["endDate"] = (now + timedelta(days=14)).isoformat()

    update_json(app, resource_name, resource_id, {"data": data})

    return resource


def update_json(app, resource_name, resource_id, data):
    app.config[resource_name + '_' + resource_id] = dumps(data)


def resource_partition(app, resource_id, resource_name='tender', part='all'):
    try:
        obj = munchify(loads(app.config[resource_name + '_' + resource_id]))
        if part == 'all':
            return obj
        else:
            return munchify(obj['data'][part])
    except (KeyError, IOError):
        return []


def location_error(name):
    return dumps(
        {
            "status": "error",
            "errors": [
                {
                    "location": "url",
                    "name": name + '_id',
                    "description": "Not Found"
                }
            ]
        }
    )
