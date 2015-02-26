import gevent.monkey
gevent.monkey.patch_all()
import os
from logging import getLogger
from apscheduler.executors.pool import ThreadPoolExecutor, ProcessPoolExecutor
from apscheduler.schedulers.gevent import GeventScheduler as Scheduler
from couchdb import Server, Session
from couchdb.http import Unauthorized, extract_credentials
from datetime import datetime, timedelta
from openprocurement.chronograph.jobstores import CouchDBJobStore
from openprocurement.chronograph.scheduler import push
from pyramid.config import Configurator
from pytz import timezone
from tzlocal import get_localzone
from pyramid.events import ApplicationCreated, ContextFound, BeforeRender


try:
    from systemd.journal import JournalHandler
except ImportError:
    JournalHandler = False

LOGGER = getLogger(__name__)
TZ = timezone(get_localzone().tzname(datetime.now()))
SECURITY = {u'admins': {u'names': [], u'roles': ['_admin']}, u'members': {u'names': [], u'roles': ['_admin']}}
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


def set_journal_handler(event):
    request = event.request
    params = {
        'TENDERS_API_URL': request.registry.api_url,
        'TAGS': 'python,chronograph',
        'CURRENT_URL': request.url,
        'CURRENT_PATH': request.path_info,
        'REMOTE_ADDR': request.remote_addr or '',
        'USER_AGENT': request.user_agent or '',
        'TENDER_ID': '',
        'TIMESTAMP': datetime.now(TZ).isoformat(),
        'REQUEST_ID': request.environ.get('REQUEST_ID', ''),
        'CLIENT_REQUEST_ID': request.headers.get('X-Client-Request-ID', ''),
    }
    if request.params:
        params['PARAMS'] = str(dict(request.params))
    if request.matchdict:
        for i, j in request.matchdict.items():
            params[i.upper()] = j
    for i in LOGGER.handlers:
        LOGGER.removeHandler(i)
    LOGGER.addHandler(JournalHandler(**params))


def clear_journal_handler(event):
    for i in LOGGER.handlers:
        LOGGER.removeHandler(i)


def start_scheduler(event):
    app = event.app
    app.registry.scheduler.start()


def main(global_config, **settings):
    """ This function returns a Pyramid WSGI application.
    """
    config = Configurator(settings=settings)
    if JournalHandler:
        config.add_subscriber(set_journal_handler, ContextFound)
        config.add_subscriber(clear_journal_handler, BeforeRender)
    config.include('pyramid_exclog')
    config.add_route('home', '/')
    config.add_route('resync_all', '/resync_all')
    config.add_route('resync', '/resync/{tender_id}')
    config.scan()
    config.add_subscriber(start_scheduler, ApplicationCreated)
    config.registry.api_token = os.environ.get('API_TOKEN', settings.get('api.token'))

    db_name = os.environ.get('DB_NAME', settings['couchdb.db_name'])
    server = Server(settings.get('couchdb.url'), session=Session(retry_delays=range(60)))
    if 'couchdb.admin_url' not in settings and server.resource.credentials:
        try:
            server.version()
        except Unauthorized:
            server = Server(extract_credentials(settings.get('couchdb.url'))[0])
    config.registry.couchdb_server = server
    if 'couchdb.admin_url' in settings and server.resource.credentials:
        aserver = Server(settings.get('couchdb.admin_url'), session=Session(retry_delays=range(10)))
        users_db = aserver['_users']
        if SECURITY != users_db.security:
            LOGGER.info("Updating users db security", extra={'MESSAGE_ID': 'update_users_security'})
            users_db.security = SECURITY
        username, password = server.resource.credentials
        user_doc = users_db.get('org.couchdb.user:{}'.format(username), {'_id': 'org.couchdb.user:{}'.format(username)})
        if not user_doc.get('derived_key', '') or PBKDF2(password, user_doc.get('salt', ''), user_doc.get('iterations', 10)).hexread(int(len(user_doc.get('derived_key', ''))/2)) != user_doc.get('derived_key', ''):
            user_doc.update({
                "name": username,
                "roles": [],
                "type": "user",
                "password": password
            })
            LOGGER.info("Updating chronograph db main user", extra={'MESSAGE_ID': 'update_chronograph_main_user'})
            users_db.save(user_doc)
        security_users = [username,]
        if db_name not in aserver:
            aserver.create(db_name)
        db = aserver[db_name]
        SECURITY[u'members'][u'names'] = security_users
        if SECURITY != db.security:
            LOGGER.info("Updating chronograph db security", extra={'MESSAGE_ID': 'update_chronograph_security'})
            db.security = SECURITY
        auth_doc = db.get(VALIDATE_DOC_ID, {'_id': VALIDATE_DOC_ID})
        if auth_doc.get('validate_doc_update') != VALIDATE_DOC_UPDATE % username:
            auth_doc['validate_doc_update'] = VALIDATE_DOC_UPDATE % username
            LOGGER.info("Updating chronograph db validate doc", extra={'MESSAGE_ID': 'update_chronograph_validate_doc'})
            db.save(auth_doc)
    else:
        if db_name not in server:
            server.create(db_name)
    config.registry.db = server[db_name]

    jobstores = {
        #'default': CouchDBJobStore(database=db_name,
                                   #client=server)
    }
    executors = {
        'default': ThreadPoolExecutor(5),
        #'processpool': ProcessPoolExecutor(5)
    }
    job_defaults = {
        'coalesce': False,
        'max_instances': 5
    }
    config.registry.api_url = settings.get('api.url')
    config.registry.callback_url = settings.get('callback.url')
    scheduler = Scheduler(jobstores=jobstores,
                          #executors=executors,
                          job_defaults=job_defaults,
                          timezone=TZ)
    scheduler.add_jobstore('sqlalchemy', url=settings['jobstore_db'])
    config.registry.scheduler = scheduler
    # scheduler.remove_all_jobs()
    # scheduler.start()
    resync_all_job = scheduler.get_job('resync_all')
    now = datetime.now(TZ)
    if not resync_all_job or resync_all_job.next_run_time < now - timedelta(hours=1):
        if resync_all_job:
            args = resync_all_job.args
        else:
            args = [settings.get('callback.url') + 'resync_all', None]
        run_date = now + timedelta(seconds=60)
        scheduler.add_job(push, 'date', run_date=run_date, timezone=TZ,
                          id='resync_all', args=args,
                          replace_existing=True, misfire_grace_time=60 * 60)
    return config.make_wsgi_app()
