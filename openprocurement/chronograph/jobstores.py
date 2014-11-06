from __future__ import absolute_import

from apscheduler.jobstores.base import BaseJobStore, JobLookupError, ConflictingIdError
from apscheduler.util import maybe_ref, datetime_to_utc_timestamp, utc_timestamp_to_datetime
from apscheduler.job import Job
from base64 import b64encode, b64decode

try:
    import cPickle as pickle
except ImportError:  # pragma: nocover
    import pickle

try:
    import couchdb
    from couchdb.design import ViewDefinition
except ImportError:  # pragma: nocover
    raise ImportError('CouchDBJobStore requires couchdb installed')


class CouchDBJobStore(BaseJobStore):

    """
    Stores jobs in a CouchDB database.

    Plugin alias: ``couchdb``

    :param str database: database to store jobs in
    :param str collection: collection to store jobs in
    :param client: a :class:`~pymongo.mongo_client.CouchClient` instance to use instead of providing connection
                   arguments
    :param int pickle_protocol: pickle protocol level to use (for serialization), defaults to the highest available
    """

    def __init__(self, database='apscheduler', collection='job', client=None,
                 pickle_protocol=pickle.HIGHEST_PROTOCOL, **connect_args):
        super(CouchDBJobStore, self).__init__()
        self.pickle_protocol = pickle_protocol

        if not database:
            raise ValueError('The "database" parameter must not be empty')
        if not collection:
            raise ValueError('The "collection" parameter must not be empty')

        self.doc_type = collection

        if client:
            self.connection = maybe_ref(client)
        else:
            self.connection = couchdb.Server(**connect_args)

        try:
            self.collection = self.connection[database]  # existing
        except:
            self.collection = self.connection.create(database)  # newly created

        self.jobs_all = ViewDefinition('jobs',
                                       'all',
                                       'function(doc){{if(doc.type=="{}") emit(doc._id, doc.job_state);}}'.format(self.doc_type))
        self.jobs_all.sync(self.collection)
        self.jobs_next_run_time = ViewDefinition('jobs',
                                                 'next_run_time',
                                                 'function(doc){{if(doc.type=="{}" && doc.next_run_time) emit(doc.next_run_time, doc.next_run_time);}}'.format(self.doc_type))
        self.jobs_next_run_time.sync(self.collection)
        self.jobs_by_next_run_time = ViewDefinition('jobs',
                                                    'by_next_run_time',
                                                    'function(doc) {{if(doc.type == "{}") emit(doc.next_run_time, doc.job_state);}}'.format(self.doc_type))
        self.jobs_by_next_run_time.sync(self.collection)

    def lookup_job(self, job_id):
        document = self.collection.get(job_id)
        if not document:
            raise JobLookupError(id)
        return self._reconstitute_job(document['job_state']) if document else None

    def get_due_jobs(self, now):
        timestamp = datetime_to_utc_timestamp(now)
        return self._get_jobs(endkey=timestamp)

    def get_next_run_time(self):
        res = [i for i in self.jobs_next_run_time(self.collection)]
        document = res[0] if res else None
        return utc_timestamp_to_datetime(document.value) if document else None

    def get_all_jobs(self):
        return self._get_jobs()

    def add_job(self, job):
        document = self.collection.get(job.id) or {}
        document.update({
            '_id': job.id,
            'type': self.doc_type,
            'next_run_time': datetime_to_utc_timestamp(job.next_run_time),
            'job_state': b64encode(pickle.dumps(job.__getstate__(), self.pickle_protocol))
        })
        try:
            self.collection.save(document)
        except Exception:
            raise ConflictingIdError(job.id)

    def update_job(self, job):
        changes = {
            'next_run_time': datetime_to_utc_timestamp(job.next_run_time),
            'job_state': b64encode(pickle.dumps(job.__getstate__(), self.pickle_protocol))
        }
        document = self.collection.get(job.id)
        if not document:
            raise JobLookupError(id)
        document.update(changes)
        self.collection.save(document)

    def remove_job(self, job_id):
        try:
            del self.collection[job_id]
        except Exception:
            raise JobLookupError(job_id)

    def remove_all_jobs(self):
        for i in self.jobs_all(self.collection):
            del self.collection[i.id]

    def shutdown(self):
        self.connection.disconnect()

    def _reconstitute_job(self, job_state):
        job_state = pickle.loads(b64decode(job_state))
        job = Job.__new__(Job)
        job.__setstate__(job_state)
        job._scheduler = self._scheduler
        job._jobstore_alias = self._alias
        return job

    def _get_jobs(self, **kwargs):
        jobs = []
        failed_job_ids = []
        docs = self.jobs_by_next_run_time(self.collection, **kwargs)
        for document in docs:
            try:
                jobs.append(self._reconstitute_job(document.value))
            except:
                self._logger.exception(
                    'Unable to restore job "%s" -- removing it', document.id)
                failed_job_ids.append(document.id)

        # Remove all the jobs we failed to restore
        if failed_job_ids:
            for i in failed_job_ids:
                self.remove_job(i)

        return jobs

    def __repr__(self):
        return '<%s (client=%s)>' % (self.__class__.__name__, self.connection)
