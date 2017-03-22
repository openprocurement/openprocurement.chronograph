import argparse
import os
from ConfigParser import ConfigParser
from couchdb import Server, Session
from couchdb.http import Unauthorized, extract_credentials
from logging import getLogger
from openprocurement.chronograph.design import sync_design
from pbkdf2 import PBKDF2

LOGGER = getLogger("{}.init".format(__name__))


SECURITY = {
    u'admins': {
        u'names': [],
        u'roles': ['_admin']
    },
    u'members': {
        u'names': [],
        u'roles': ['_admin']
    }
}
VALIDATE_DOC_ID = '_design/_auth'
VALIDATE_DOC_UPDATE = """function(newDoc, oldDoc, userCtx){
    if(newDoc._deleted) {
        throw({forbidden: 'Not authorized to delete this document'});
    }
    if(userCtx.roles.indexOf('_admin') !== -1 && newDoc.indexOf('_design/') === 0) {
        return;
    }
    if(userCtx.name === '%s') {
        return;
    } else {
        throw({forbidden: 'Only authorized user may edit the database'});
    }
}"""


def set_chronograph_security(settings):
    db_name = os.environ.get('DB_NAME', settings['couchdb.db_name'])
    server = Server(settings.get('couchdb.url'),
                    session=Session(retry_delays=range(60)))
    if 'couchdb.admin_url' not in settings and server.resource.credentials:
        try:
            server.version()
        except Unauthorized:
            server = Server(extract_credentials(
                settings.get('couchdb.url'))[0],
                session=Session(retry_delays=range(60)))
    if 'couchdb.admin_url' in settings and server.resource.credentials:
        aserver = Server(settings.get('couchdb.admin_url'),
                         session=Session(retry_delays=range(10)))
        users_db = aserver['_users']
        if SECURITY != users_db.security:
            LOGGER.info("Updating users db security",
                        extra={'MESSAGE_ID': 'update_users_security'})
            users_db.security = SECURITY
        username, password = server.resource.credentials
        user_doc = users_db.get(
            'org.couchdb.user:{}'.format(username),
            {'_id': 'org.couchdb.user:{}'.format(username)})
        if (not user_doc.get('derived_key', '') or
                PBKDF2(password, user_doc.get('salt', ''),
                       user_doc.get('iterations', 10)).hexread(
                           int(len(user_doc.get('derived_key', '')) / 2)) !=
                user_doc.get('derived_key', '')):
            user_doc.update({
                "name": username,
                "roles": [],
                "type": "user",
                "password": password
            })
            LOGGER.info("Updating chronograph db main user",
                        extra={'MESSAGE_ID': 'update_chronograph_main_user'})
            users_db.save(user_doc)
        security_users = [username, ]
        if db_name not in aserver:
            aserver.create(db_name)
        db = aserver[db_name]
        SECURITY[u'members'][u'names'] = security_users
        if SECURITY != db.security:
            LOGGER.info("Updating chronograph db security",
                        extra={'MESSAGE_ID': 'update_chronograph_security'})
            db.security = SECURITY
        auth_doc = db.get(VALIDATE_DOC_ID, {'_id': VALIDATE_DOC_ID})
        if auth_doc.get('validate_doc_update') != VALIDATE_DOC_UPDATE % username:
            auth_doc['validate_doc_update'] = VALIDATE_DOC_UPDATE % username
            LOGGER.info("Updating chronograph db validate doc",
                        extra={'MESSAGE_ID': 'update_chronograph_validate_doc'})
            db.save(auth_doc)
        # sync couchdb views
        sync_design(db)
        db = server[db_name]
    else:
        if db_name not in server:
            server.create(db_name)
        db = server[db_name]
        # sync couchdb views
        sync_design(db)
    return server, db


def bootstrap_chronograph_security():
    parser = argparse.ArgumentParser(description='---- Bootstrap Chronograph Security ----')
    parser.add_argument('section', type=str, help='Section in configuration file')
    parser.add_argument('config', type=str, help='Path to configuration file')
    params = parser.parse_args()
    if os.path.isfile(params.config):
        conf = ConfigParser()
        conf.read(params.config)
        settings = {k: v for k, v in conf.items(params.section)}
        set_chronograph_security(settings)
