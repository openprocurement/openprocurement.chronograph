# -*- coding: utf-8 -*-
from couchdb.design import ViewDefinition
from openprocurement.chronograph.constants import (
    INSIDER_WORKING_DAY_START, TEXAS_WORKING_DAY_START
)


def sync_design(db):
    views = [j for i, j in globals().items() if "_view" in i]
    ViewDefinition.sync_many(db, views)


plan_auctions_view = ViewDefinition('plan', 'auctions', '''function(doc) {
    if(doc.streams || doc.dutch_streams) {
        for (var i in doc) {
            if (i.indexOf('stream_') == 0) {
                for (var t in doc[i]) {
                    if (doc[i][t]) {
                        var x = doc[i][t].split('_')
                        if (x.length == 2) {
                            emit(x, doc._id.split('_')[1] + 'T' + t);
                        } else {
                            emit([x[0], null],
                                 doc._id.split('_')[1] + 'T' + t);
                        }
                    }
                }
            }
            if (i.indexOf('dutch_streams') == 0) {
                for (var aid in doc[i]) {
                    emit([doc[i][aid], null],
                          doc._id.split('_')[1] + 'T' + '%s');
                }
            }
            if (i.indexOf('texas_streams') == 0) {
                for (var aid in doc[i]) {
                    emit([doc[i][aid], null],
                          doc._id.split('_')[1] + 'T' + '%s');
                }
            }
        };
    }
}''' % (INSIDER_WORKING_DAY_START.isoformat(), TEXAS_WORKING_DAY_START.isoformat()))
