# -*- coding: utf-8 -*-
from datetime import timedelta

from openprocurement.chronograph.tests.utils import now

test_auction_data = {
    "auctionID": "UA-EA-{}-000001".format(now.strftime('%Y-%m-%d')),
    "awardCriteria": "highestCost",
    "date": now.isoformat(),
    "dateModified": now.isoformat(),
    "id": "f547ece35436484e8656a2988fb52a44",
    "status": "active.enquiries",
    "submissionMethod": "electronicAuction",
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
    "next_check": (now + timedelta(days=7)).isoformat(),
    "owner": "test",
    "procurementMethod": "open",
    "value": {
        "amount": 500,
        "currency": u"UAH",
        "valueAddedTaxIncluded": True
    },
    "minimalStep": {
        "amount": 35,
        "currency": u"UAH",
        "valueAddedTaxIncluded": True
    },
    "items": [
        {
            "description": u"футляри до державних нагород",
            "classification": {
                "scheme": u"CAV",
                "id": u"70122000-2",
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
            "quantity": 5,
            "id": "181f08dbe3944325a1bb272e756f04cb"

        }
    ],
    "enquiryPeriod": {
        "endDate": (now + timedelta(days=7)).isoformat(),
        "startDate": now.isoformat()
    },
    "tenderPeriod": {
        "startDate": (now + timedelta(days=7)).isoformat(),
        "endDate": (now + timedelta(days=14)).isoformat()
    }
}

test_lots = [
    {
        "title": "lot title",
        "description": "lot description",
        "value": test_auction_data["value"],
        "minimalStep": test_auction_data["minimalStep"],
        "id": "20e0201d81af4aaeb33546f04744d493",
        "status": "active"
    }
]

test_bids = [
    {
        "id": "1d1caac9baa7445f90ca1ba06a1c605c",
        "owner": "test",
        "status": "active",
        "tenderers": [
            test_auction_data["procuringEntity"]
        ],
        "value": {
            "amount": 469,
            "currency": "UAH",
            "valueAddedTaxIncluded": True
        }
    },
    {
        "id": "cc15a3d3ad204143abe1ea0dd69a108e",
        "owner": "test",
        "status": "active",
        "tenderers": [
            test_auction_data["procuringEntity"]
        ],
        "value": {
            "amount": 479,
            "currency": "UAH",
            "valueAddedTaxIncluded": True
        }
    }
]

plantest = {
   "_id": "plantest_2017-10-03",
   "dutch_streams": [
       "01fa8a7dc4b8eac3b5820747efc6fe36",
       "442000d99bf203ddfd62b3be58350383",
       "01fa8a7dc4b8eac3b5820747efc6fe36",
       "da8a28ed2bdf73ee1d373e4cadfed4c5",
       "01fa8a7dc4b8eac3b5820747efc6fe36",
       "442000d99bf203ddfd62b3be58350383",
       "01fa8a7dc4b8eac3b5820747efc6fe36",
       "da8a28ed2bdf73ee1d373e4cadfed4c5",
       "01fa8a7dc4b8eac3b5820747efc6fe36",
       "442000d99bf203ddfd62b3be58350383",
       "01fa8a7dc4b8eac3b5820747efc6fe36",
       "da8a28ed2bdf73ee1d373e4cadfed4c5",
       "01fa8a7dc4b8eac3b5820747efc6fe36",
       "01fa8a7dc4b8eac3b5820747efc6fe36",
       "01fa8a7dc4b8eac3b5820747efc6fe36"
   ],
    "stream_1": {
        "12:00:00": "01fa8a7dc4b8eac3b5820747efc6fe36",
        "12:30:00": "da8a28ed2bdf73ee1d373e4cadfed4c5_1c2fb1e496b317b2b87e197e2332da77",
        "13:00:00": "e51508cddc2c490005eaecb73c006b72",
        "13:30:00": "e51508cddc2c490005eaecb73c006b72",
        "11:30:00": "e51508cddc2c490005eaecb73c006b72",
        "11:00:00": "01fa8a7dc4b8eac3b5820747efc6fe36",
        "15:30:00": "e51508cddc2c490005eaecb73c006b72",
        "15:00:00": "da8a28ed2bdf73ee1d373e4cadfed4c5_1c2fb1e496b317b2b87e197e2332da77",
        "14:00:00": "da8a28ed2bdf73ee1d373e4cadfed4c5_b10f9f7f26157ae2f349be8dc2106d6e",
        "14:30:00": "01fa8a7dc4b8eac3b5820747efc6fe36"
    },
    "stream_2": {
        "12:00:00": "01fa8a7dc4b8eac3b5820747efc6fe36",
        "12:30:00": "da8a28ed2bdf73ee1d373e4cadfed4c5_1c2fb1e496b317b2b87e197e2332da77",
        "13:00:00": "e51508cddc2c490005eaecb73c006b72",
        "13:30:00": "01fa8a7dc4b8eac3b5820747efc6fe36",
        "11:30:00": "da8a28ed2bdf73ee1d373e4cadfed4c5_b10f9f7f26157ae2f349be8dc2106d6e",
        "11:00:00": "e51508cddc2c490005eaecb73c006b72",
        "15:30:00": "e51508cddc2c490005eaecb73c006b72",
        "15:00:00": "01fa8a7dc4b8eac3b5820747efc6fe36",
        "14:00:00": "da8a28ed2bdf73ee1d373e4cadfed4c5_1c2fb1e496b317b2b87e197e2332da77",
        "14:30:00": "01fa8a7dc4b8eac3b5820747efc6fe36"
    },
    "streams": 2
}
