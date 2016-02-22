# -*- coding: utf-8 -*-
from couchdb.design import ViewDefinition


def sync_design(db):
    views = [j for i, j in globals().items() if "_view" in i]
    ViewDefinition.sync_many(db, views)


plan_tenders_view = ViewDefinition('plan', 'tenders', '''function(doc) {
    if(doc.streams) {
        for (var i in doc) {
            if (i.indexOf('stream_') == 0) {
                for (var t in doc[i]) {
                    var x = doc[i][t].split('_')
                    if (x.length == 2) {
                        emit(x, doc._id.split('_')[1] + 'T' + t);
                    } else {
                        emit([x[0], null], doc._id.split('_')[1] + 'T' + t);
                    }
                }
            }
        };
    }
}''')
