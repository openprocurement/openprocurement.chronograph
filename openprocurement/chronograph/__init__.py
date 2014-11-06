from apscheduler.executors.pool import ThreadPoolExecutor, ProcessPoolExecutor
from apscheduler.schedulers.background import BackgroundScheduler
from couchdb import Server
from datetime import datetime, timedelta
from openprocurement.chronograph.jobstores import CouchDBJobStore
from openprocurement.chronograph.scheduler import push
from pyramid.config import Configurator
from pytz import utc
from time import time


def main(global_config, **settings):
    """ This function returns a Pyramid WSGI application.
    """
    config = Configurator(settings=settings)
    config.add_route('home', '/')
    config.add_route('resync_all', '/resync_all')
    config.add_route('resync', '/resync/{id}')
    config.scan()
    server = Server(settings.get('couchdb.url'))
    config.registry.couchdb_server = server
    jobstores = {
        'default': CouchDBJobStore(database=settings['couchdb.db_name'],
                                   client=server)
    }
    executors = {
        'default': ThreadPoolExecutor(5),
        'processpool': ProcessPoolExecutor(5)
    }
    job_defaults = {
        'coalesce': False,
        'max_instances': 5
    }
    config.registry.api_url = settings.get('api.url')
    config.registry.callback_url = settings.get('callback.url')
    scheduler = BackgroundScheduler(jobstores=jobstores,
                                    executors=executors,
                                    job_defaults=job_defaults,
                                    timezone=utc)
    config.registry.scheduler = scheduler
    scheduler.remove_all_jobs()
    scheduler.start()
    resync_all_job = scheduler.get_job('resync_all')
    if not resync_all_job:
        run_date = datetime.utcfromtimestamp(time()) + timedelta(seconds=60)
        scheduler.add_job(push, 'date', run_date=run_date, timezone=utc,
                          id='resync_all',
                          args=[settings.get('callback.url') + 'resync_all', None],
                          replace_existing=True)
    return config.make_wsgi_app()
