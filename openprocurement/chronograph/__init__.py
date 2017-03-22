import gevent.monkey
gevent.monkey.patch_all()
import os
from logging import getLogger
# from apscheduler.executors.pool import ThreadPoolExecutor, ProcessPoolExecutor
from apscheduler.schedulers.gevent import GeventScheduler as Scheduler
from datetime import datetime, timedelta
# from openprocurement.chronograph.jobstores import CouchDBJobStore
from openprocurement.chronograph.database import set_chronograph_security
from openprocurement.chronograph.scheduler import push
from openprocurement.chronograph.utils import add_logging_context
from pyramid.config import Configurator
from pytz import timezone
from pyramid.events import ApplicationCreated, ContextFound

LOGGER = getLogger(__name__)

TZ = timezone(os.environ['TZ'] if 'TZ' in os.environ else 'Europe/Kiev')



def start_scheduler(event):
    app = event.app
    app.registry.scheduler.start()


def main(global_config, **settings):
    """ This function returns a Pyramid WSGI application.
    """
    config = Configurator(settings=settings)
    config.add_subscriber(add_logging_context, ContextFound)
    config.include('pyramid_exclog')
    config.add_route('home', '/')
    config.add_route('resync_all', '/resync_all')
    config.add_route('resync_back', '/resync_back')
    config.add_route('resync', '/resync/{tender_id}')
    config.add_route('recheck', '/recheck/{tender_id}')
    config.add_route('calendar', '/calendar')
    config.add_route('calendar_entry', '/calendar/{date}')
    config.add_route('streams', '/streams')
    config.scan(ignore='openprocurement.chronograph.tests')
    config.add_subscriber(start_scheduler, ApplicationCreated)
    config.registry.api_token = os.environ.get('API_TOKEN', settings.get('api.token'))

    server, db = set_chronograph_security(settings)
    config.registry.couchdb_server = server
    config.registry.db = db

    jobstores = {
        #'default': CouchDBJobStore(database=db_name, client=server)
    }
    #executors = {
        #'default': ThreadPoolExecutor(5),
        #'processpool': ProcessPoolExecutor(5)
    #}
    job_defaults = {
        'coalesce': False,
        'max_instances': 3
    }
    config.registry.api_url = settings.get('api.url')
    config.registry.callback_url = settings.get('callback.url')
    scheduler = Scheduler(jobstores=jobstores,
                          #executors=executors,
                          job_defaults=job_defaults,
                          timezone=TZ)
    if 'jobstore_db' in settings:
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
