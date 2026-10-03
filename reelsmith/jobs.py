"""Persistent job queue.

Every job is a JSON file in <output>/_jobs/. One background worker takes the oldest queued job, runs it, and
records status, stage, progress, log and results as it goes, so the list survives restarts:
  * queued jobs are picked up again on start,
  * a job that was running when the server stopped is marked "interrupted" (retry creates a fresh job),
  * finished videos from before the job list existed are imported so they show up in the history.
"""
import json
import os
import shutil
import threading
import time
import traceback
import uuid

ACTIVE = ('queued', 'running')
SUMMARY_KEYS = ('id', 'kind', 'title', 'status', 'stage', 'progress', 'created', 'started', 'finished', 'error',
                'options', 'retry_of', 'cancel_requested')


class JobStore:
    def __init__(self, out_root, runner):
        """runner(job_dict, hooks) -> result dict. hooks: log(msg), progress(stage, frac), cancelled() -> bool."""
        self.out = os.path.abspath(out_root)
        self.dir = os.path.join(self.out, '_jobs')
        os.makedirs(self.dir, exist_ok=True)
        self.runner = runner
        self.lock = threading.RLock()
        self.wake = threading.Condition(self.lock)
        self.jobs, self._last_write = {}, {}
        self._load()
        threading.Thread(target=self._loop, daemon=True, name='reelsmith-worker').start()

    # ---------------------------------------------------------------- persistence
    def _file(self, jid): return os.path.join(self.dir, f'{jid}.json')

    def _write(self, j, force=True):
        now = time.time()
        if not force and now - self._last_write.get(j['id'], 0) < 1.0: return
        self._last_write[j['id']] = now
        tmp = self._file(j['id']) + '.tmp'
        with open(tmp, 'w') as f: json.dump(j, f, ensure_ascii=False)
        os.replace(tmp, self._file(j['id']))

    def _load(self):
        for name in os.listdir(self.dir):
            if not name.endswith('.json'): continue
            try:
                j = json.load(open(os.path.join(self.dir, name)))
            except (OSError, json.JSONDecodeError):
                continue
            if j.get('status') == 'running':
                j.update(status='interrupted', stage='interrupted', finished=time.time(),
                         error='The server stopped while this job was running. Retry to run it again.')
                self._write(j)
            self.jobs[j['id']] = j
        # import finished videos made before the job list existed
        known = {(j.get('result') or {}).get('manifest', {}).get('job') for j in self.jobs.values()}
        for d in os.listdir(self.out):
            m = os.path.join(self.out, d, 'manifest.json')
            if d.startswith('_') or d in known or not os.path.exists(m): continue
            try: man = json.load(open(m))
            except (OSError, json.JSONDecodeError): continue
            jid = 'imp' + uuid.uuid5(uuid.NAMESPACE_URL, d).hex[:7]
            created = os.path.getmtime(m)
            j = {'id': jid, 'kind': 'imported', 'title': man.get('name', d), 'status': 'done', 'stage': 'done', 'progress': 1.0,
                 'created': created, 'started': created, 'finished': created, 'error': None, 'log': ['Imported from an earlier run.'],
                 'payload': {}, 'options': self._options(man), 'result': self._result(man, d), 'retry_of': None, 'cancel_requested': False}
            self.jobs[jid] = j; self._write(j)

    @staticmethod
    def _options(m):
        return {'duration': m.get('duration'), 'quality': m.get('quality'), 'upscale': m.get('upscale'), 'template': m.get('template'),
                'voiceover': m.get('voiceover', False), 'resolution': m.get('resolution')}

    def _result(self, manifest, job_dir, sb=None, caps=None):
        def load(name):
            try: return json.load(open(os.path.join(self.out, job_dir, name)))
            except (OSError, json.JSONDecodeError): return None
        return {'manifest': manifest, 'base': f'/files/{job_dir}/',
                'storyboard': sb if sb is not None else load('storyboard.json'),
                'captions': caps if caps is not None else load('captions.json')}

    # ---------------------------------------------------------------- public api
    def submit(self, kind, payload):
        title = (payload.get('storyboard') or {}).get('name') if kind == 'render' else None
        title = title or payload.get('topic') or payload.get('url') or (payload.get('description') or '')[:60] or 'Untitled'
        j = {'id': uuid.uuid4().hex[:10], 'kind': kind, 'title': str(title)[:80], 'status': 'queued', 'stage': 'queued',
             'progress': 0.0, 'created': time.time(), 'started': None, 'finished': None, 'error': None, 'log': [],
             'payload': payload, 'result': None, 'retry_of': payload.pop('_retry_of', None), 'cancel_requested': False,
             'options': {'duration': payload.get('duration') or (payload.get('storyboard') or {}).get('duration'),
                         'quality': payload.get('quality') or 'final', 'upscale': payload.get('upscale') or None,
                         'voiceover': bool(payload.get('voiceover')), 'voice': payload.get('voice') or None,
                         'template': payload.get('template') or (payload.get('storyboard') or {}).get('template') or 'midnight'}}
        with self.lock:
            self.jobs[j['id']] = j; self._write(j); self.wake.notify_all()
        return j['id']

    def summary(self, j):
        out = {k: j.get(k) for k in SUMMARY_KEYS}
        r = j.get('result') or {}
        if r:
            m = r.get('manifest') or {}
            out['result'] = {'base': r.get('base'), 'files': m.get('files'), 'resolution': m.get('resolution'),
                             'seconds': m.get('seconds'), 'name': m.get('name')}
        out['position'] = self.position(j['id']) if j['status'] == 'queued' else None
        return out

    def list(self):
        with self.lock:
            return [self.summary(j) for j in sorted(self.jobs.values(), key=lambda j: -j['created'])]

    def get(self, jid):
        with self.lock:
            j = self.jobs.get(jid)
            if not j: return None
            out = json.loads(json.dumps(j))
            out['position'] = self.position(jid) if j['status'] == 'queued' else None
            return out

    def position(self, jid):
        q = sorted((j for j in self.jobs.values() if j['status'] == 'queued'), key=lambda j: j['created'])
        return next((i + 1 for i, j in enumerate(q) if j['id'] == jid), None)

    def cancel(self, jid):
        with self.lock:
            j = self.jobs.get(jid)
            if not j: raise KeyError(jid)
            if j['status'] == 'queued':
                j.update(status='cancelled', stage='cancelled', finished=time.time()); self._write(j)
            elif j['status'] == 'running':
                j['cancel_requested'] = True; j['log'].append('Cancel requested…'); self._write(j)
            else:
                raise ValueError(f"This job is {j['status']}; only queued or running jobs can be cancelled.")
            return self.summary(j)

    def retry(self, jid):
        with self.lock:
            j = self.jobs.get(jid)
            if not j: raise KeyError(jid)
            if j['status'] in ACTIVE: raise ValueError('This job is still queued or running.')
            if not j.get('payload'): raise ValueError('This job was imported from an earlier run and has no recorded inputs to retry.')
            payload = json.loads(json.dumps(j['payload'])); payload['_retry_of'] = jid
            return self.submit(j['kind'], payload)

    def delete(self, jid, files=False):
        with self.lock:
            j = self.jobs.get(jid)
            if not j: raise KeyError(jid)
            if j['status'] in ACTIVE: raise ValueError('Cancel the job before deleting it.')
            if files:
                d = ((j.get('result') or {}).get('manifest') or {}).get('dir') or ''
                d = os.path.realpath(os.path.join(self.out, os.path.basename(d.rstrip('/')))) if d else ''
                if d and d.startswith(self.out + os.sep) and os.path.isdir(d): shutil.rmtree(d, ignore_errors=True)
            self.jobs.pop(jid, None)
            try: os.remove(self._file(jid))
            except FileNotFoundError: pass

    # ---------------------------------------------------------------- worker
    def _next(self):
        q = [j for j in self.jobs.values() if j['status'] == 'queued']
        return min(q, key=lambda j: j['created']) if q else None

    def _loop(self):
        while True:
            with self.lock:
                j = self._next()
                while j is None:
                    self.wake.wait(); j = self._next()
                j.update(status='running', stage='starting', started=time.time()); self._write(j)
                jid = j['id']

            def log(msg, jid=jid):
                with self.lock:
                    jj = self.jobs.get(jid)
                    if jj: jj['log'].append(str(msg)); self._write(jj, force=False)

            def progress(stage, frac, jid=jid):
                with self.lock:
                    jj = self.jobs.get(jid)
                    if jj: jj.update(stage=stage, progress=round(float(frac), 3)); self._write(jj, force=False)

            def cancelled(jid=jid):
                with self.lock:
                    jj = self.jobs.get(jid); return bool(jj and jj.get('cancel_requested'))

            try:
                manifest, sb, caps = self.runner(j, {'log': log, 'progress': progress, 'cancelled': cancelled})
                res = self._result(manifest, manifest['job'], sb, caps)
                with self.lock:
                    j.update(status='done', stage='done', progress=1.0, finished=time.time(), result=res,
                             options={**j['options'], 'resolution': manifest.get('resolution')})
                    self._write(j)
            except Exception as e:
                was_cancel = type(e).__name__ == 'Cancelled' or cancelled()
                with self.lock:
                    if was_cancel:
                        j.update(status='cancelled', stage='cancelled', finished=time.time())
                        j['log'].append('Cancelled.')
                    else:
                        j.update(status='error', stage='error', finished=time.time(), error=str(e) or type(e).__name__)
                        j['log'].append(traceback.format_exc(limit=4))
                    self._write(j)
