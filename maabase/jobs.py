"""Bounded local calculation queue; polling never waits for the optimizer."""
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
import threading
from time import monotonic
from uuid import uuid4


class JobStore:
    def __init__(self, max_pending=4, ttl=3600):
        self.executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix='maabase-calculation')
        self.lock = threading.RLock()
        self.jobs = {}
        self.max_pending, self.ttl = max_pending, ttl

    def submit(self, fn, payload):
        with self.lock:
            now = monotonic()
            self.jobs = {key: job for key, job in self.jobs.items()
                         if job['status'] in {'queued', 'running'} or now - job['updated'] < self.ttl}
            finished = [key for key, job in self.jobs.items() if job['status'] not in {'queued', 'running'}]
            for key in finished[:-8]:
                del self.jobs[key]
            if sum(job['status'] in {'queued', 'running'} for job in self.jobs.values()) >= self.max_pending:
                raise ValueError('已有计算正在排队，请等本次计算完成')
            job_id = uuid4().hex
            self.jobs[job_id] = {'id': job_id, 'status': 'queued', 'updated': now,
                                 'progress': {'stage': 'queued', 'detail': '等待前一项计算完成',
                                              'elapsed_seconds': 0, 'stage_seconds': {}}}
            self.jobs[job_id]['future'] = self.executor.submit(self._run, job_id, fn, deepcopy(payload))
            return job_id

    def _run(self, job_id, fn, payload):
        def progress(report):
            with self.lock:
                self.jobs[job_id].update(progress=report, updated=monotonic())
        with self.lock:
            self.jobs[job_id]['status'] = 'running'
        try:
            # Decorated calculations accept progress without changing their
            # existing positional API. Keep simple callables usable in tests.
            result = fn(payload, progress=progress) if hasattr(fn, '__wrapped__') else fn(payload)
            with self.lock:
                self.jobs[job_id].update(status='completed', result=result, updated=monotonic())
        except Exception as exc:
            with self.lock:
                self.jobs[job_id].update(status='failed', error=str(exc), updated=monotonic())

    def get(self, job_id):
        with self.lock:
            job = self.jobs[job_id]
            report = deepcopy({k: v for k, v in job.items() if k not in {'future', 'result', 'updated'}})
            if job['status'] == 'running':
                elapsed = monotonic() - job['updated']
                report['progress']['elapsed_seconds'] += elapsed
                name = report['progress']['stage']
                if name not in {'preparing', 'queued'}:
                    times = report['progress']['stage_seconds']
                    times[name] = times.get(name, 0) + elapsed
            return report

    def result(self, job_id):
        with self.lock:
            job = self.jobs[job_id]
            if job['status'] != 'completed':
                raise ValueError(job.get('error') or '计算尚未完成')
            return job['result']

    def wait(self, job_id, timeout=None):
        self.jobs[job_id]['future'].result(timeout)

    def close(self):
        self.executor.shutdown(wait=True)
