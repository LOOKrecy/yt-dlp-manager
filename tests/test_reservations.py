import io
import json
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
from fastapi import HTTPException

from app.models import DownloadRequest
from app.path_utils import windows_path_key
from app.process_manager import DownloadConflict, DownloadJob, ProcessManager


def request(tmp_path, **updates):
    return DownloadRequest(url='https://example.test/video/1', download_dir=str(tmp_path), filename_template='same', download_mode='manual', selected_format='137+140', **updates)


def held_manager(monkeypatch):
    manager = ProcessManager()
    launches = []
    monkeypatch.setattr(manager, '_launch', lambda job: launches.append((job.id, job.run_id)))
    return manager, launches


def end(manager, job, status='error'):
    manager._finish(job, status, status)
    manager._release(job, job.run_id)


@pytest.mark.parametrize('status', ['error', 'stopped', 'success'])
def test_terminal_status_keeps_lease_until_worker_cleanup(tmp_path, monkeypatch, status):
    manager, launches = held_manager(monkeypatch)
    req = request(tmp_path)
    job = manager.jobs[manager.start_download(req)]
    manager._finish(job, status, 'done')
    with pytest.raises(DownloadConflict) as conflict:
        manager.start_download(req)
    assert conflict.value.detail['code'] == 'path_active'
    manager._release(job, job.run_id)
    assert not manager._reserved
    assert manager._partial_owners[windows_path_key(job.output_template)] == job.id


def test_load_history_without_active_reserves_preserves_artifacts(tmp_path, monkeypatch):
    import app.process_manager as module
    manager, _ = held_manager(monkeypatch)
    job = manager.jobs[manager.start_download(request(tmp_path))]
    partial = tmp_path / 'same.f137.mp4.part'; partial.write_bytes(b'keep')
    track = tmp_path / 'same.f140.m4a'; track.write_bytes(b'track')
    job.manifest.append(str(track)); manager._persist()
    reloaded = ProcessManager()
    assert not reloaded._reserved
    assert reloaded.jobs[job.id].status == 'interrupted'
    assert reloaded.jobs[job.id].output_template == job.output_template
    assert reloaded.jobs[job.id].manifest == [str(track)]
    assert partial.read_bytes() == b'keep' and track.read_bytes() == b'track'
    with pytest.raises(DownloadConflict) as conflict: reloaded.start_download(request(tmp_path))
    assert conflict.value.detail['code'] == 'resume_available'


def test_compatible_start_offers_same_job_and_card_retry_preserves_history(tmp_path, monkeypatch):
    manager, launches = held_manager(monkeypatch)
    req = request(tmp_path)
    job = manager.jobs[manager.start_download(req)]
    job.attempt = 5; job.attempts.append({'number': 5}); end(manager, job)
    partial = tmp_path / 'same.mp4.part'; partial.write_bytes(b'old bytes')
    with pytest.raises(DownloadConflict) as conflict: manager.start_download(req)
    assert conflict.value.detail == {'code': 'resume_available', 'owner_job_id': job.id, 'actions': ['resume', 'rename'], 'message': 'Продолжить существующее задание'}
    template = job.output_template
    assert manager.retry(job.id)
    assert job.id == launches[-1][0] and job.output_template == template
    assert job.attempt == 5 and job.attempts == [{'number': 5}] and job.resuming
    assert partial.read_bytes() == b'old bytes'


@pytest.mark.parametrize('updates', [
    {'url':'https://example.test/video/2'}, {'selected_format':'136+140'},
    {'section_enabled':True,'section_end':'00:00:10'}, {'section_keyframe_fix':False},
    {'audio_format':'wav'}, {'extra_args':'--recode-video mkv'},
    {'download_mode':'audio'}, {'cookies_enabled':True,'cookies_file':'other'},
])
def test_result_changes_do_not_adopt_partial(tmp_path, monkeypatch, updates):
    manager, launches = held_manager(monkeypatch)
    req = request(tmp_path)
    job = manager.jobs[manager.start_download(req)]; end(manager, job)
    part = tmp_path / 'same.f137.mp4.part'; part.write_bytes(b'unchanged')
    with pytest.raises(DownloadConflict) as conflict: manager.start_download(req.model_copy(update=updates))
    assert conflict.value.detail['code'] == 'partial_incompatible'
    assert conflict.value.detail['actions'] == ['rename']
    assert len(launches) == 1 and part.read_bytes() == b'unchanged'


def test_auto_selection_never_claims_compatible_but_card_can_use_pinned_ids(tmp_path, monkeypatch):
    manager, _ = held_manager(monkeypatch)
    req = request(tmp_path).model_copy(update={'download_mode':'video','selected_format':''})
    job = manager.jobs[manager.start_download(req)]; job.attempt = 1; end(manager, job)
    with pytest.raises(DownloadConflict) as conflict: manager.start_download(req)
    assert conflict.value.detail['code'] == 'partial_incompatible'
    with pytest.raises(DownloadConflict) as conflict: manager.retry(job.id)
    assert conflict.value.detail['code'] == 'selection_unresolved'
    job.resolved_format = '137+140'
    assert manager.retry(job.id)


@pytest.mark.parametrize('race', ['start/start','start/retry','retry/retry'])
def test_competing_requests_have_one_launch(tmp_path, monkeypatch, race):
    manager, launches = held_manager(monkeypatch)
    req = request(tmp_path)
    old = None
    if race != 'start/start':
        old = manager.jobs[manager.start_download(req)]; end(manager, old); launches.clear()
    barrier = threading.Barrier(2)
    def call(action):
        barrier.wait(timeout=3)
        try: return manager.start_download(req) if action == 'start' else manager.retry(old.id)
        except DownloadConflict: return False
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(call, race.split('/')))
    assert len(launches) == 1 and sum(bool(x) for x in results) == 1
    assert len(manager._reserved) == 1


def test_old_retry_and_late_release_cannot_steal_new_owner(tmp_path, monkeypatch):
    manager, launches = held_manager(monkeypatch)
    req = request(tmp_path)
    old = manager.jobs[manager.start_download(req)]; old_run = old.run_id; end(manager, old, 'success')
    new = manager.jobs[manager.start_download(req)]
    old.status = 'error'
    with pytest.raises(DownloadConflict) as conflict: manager.retry(old.id)
    assert conflict.value.detail['owner_job_id'] == new.id
    manager._release(old, old_run)
    assert manager._reserved[windows_path_key(new.output_template)] == (new.id, new.run_id)
    end(manager, new)
    with pytest.raises(DownloadConflict) as conflict: manager.retry(old.id)
    assert conflict.value.detail['code'] == 'partial_incompatible'
    assert len(launches) == 2


def test_same_job_late_release_checks_run_id(tmp_path, monkeypatch):
    manager, _ = held_manager(monkeypatch)
    job = manager.jobs[manager.start_download(request(tmp_path))]; old_run = job.run_id; end(manager, job)
    manager.retry(job.id); manager._release(job, old_run)
    assert job.worker_active and manager._reserved[windows_path_key(job.output_template)] == (job.id, job.run_id)


def test_windows_path_keys_normalize_case_slashes_and_components():
    assert windows_path_key(r'C:\Downloads\folder\..\VIDEO.%(ext)s') == windows_path_key('c:/downloads/video.%(ext)s')
    assert windows_path_key('Downloads/./video.%(ext)s') == windows_path_key(Path(__file__).parents[1] / 'Downloads' / 'video.%(ext)s')
    assert windows_path_key(r'\\Server\Share\Dir\..\FILE') == windows_path_key('//server/share/file')


def test_unowned_partial_and_success_leftovers_are_not_adopted(tmp_path, monkeypatch):
    manager, launches = held_manager(monkeypatch)
    part = tmp_path / 'same.mp4.part'; part.write_bytes(b'unknown')
    with pytest.raises(DownloadConflict): manager.start_download(request(tmp_path))
    assert not launches and part.read_bytes() == b'unknown'


def test_retry_at_attempt_zero_never_reenables_force_overwrite(tmp_path, monkeypatch):
    import app.process_manager as module
    import app.ytdlp_service as service
    tool = tmp_path / 'yt-dlp.exe'; tool.write_bytes(b'fake')
    monkeypatch.setattr(service, 'YT_DLP_PATH', tool)
    manager, launches = held_manager(monkeypatch)
    job = manager.jobs[manager.start_download(request(tmp_path, conflict_policy='overwrite', resume_policy='restart'))]
    end(manager, job, 'stopped'); manager.retry(job.id)
    args = []
    def attempt(target, argv, attempt_id): args.extend(argv); return 1, ''
    monkeypatch.setattr(manager, '_run_attempt', attempt)
    job.request.auto_retry = False
    manager._worker(job)
    assert '--continue' in args and '--no-continue' not in args and '--force-overwrites' not in args
    assert job.attempt == 1 and not manager._reserved


def test_read_exception_reaps_writer_before_releasing(tmp_path, monkeypatch):
    import app.process_manager as module
    manager, launches = held_manager(monkeypatch)
    job = manager.jobs[manager.start_download(request(tmp_path))]
    observations = []
    class Output:
        def __iter__(self): raise OSError('read failed')
        def close(self): pass
    class Process:
        stdout = Output()
        running = True
        def poll(self): return None if self.running else 1
        def terminate(self):
            observations.append(bool(manager._reserved)); self.running = False
        def wait(self, timeout=None): assert not self.running; return 1
    manager._popen = lambda *a, **kw: Process()
    monkeypatch.setattr(module, 'build_download_command', lambda *a: ['yt-dlp'])
    manager._worker(job)
    assert job.status == 'error' and observations == [True] and not manager._reserved


def test_api_start_returns_structured_resume_and_retry_reuses_job(tmp_path, monkeypatch):
    import app.main as main
    manager, launches = held_manager(monkeypatch)
    monkeypatch.setattr(main, 'manager', manager)
    monkeypatch.setattr(main, '_probe_output_path', lambda req: (tmp_path/'same.mp4','',''))
    monkeypatch.setattr(main, 'save_config', lambda config: None)
    req = request(tmp_path)
    first = main.start_download(req); job = manager.jobs[first['job_id']]; end(manager, job)
    with pytest.raises(HTTPException) as conflict: main.start_download(req)
    assert conflict.value.status_code == 409 and conflict.value.detail['code'] == 'resume_available'
    assert main.retry_download(conflict.value.detail['owner_job_id'])['success']
    assert len(manager.jobs) == 1 and launches[0][0] == launches[1][0]
    with pytest.raises(HTTPException) as active: main.start_download(req)
    assert active.value.detail['code'] == 'path_active'


def test_finished_file_conflict_is_independent_of_job_lock(tmp_path, monkeypatch):
    import app.main as main
    manager, launches = held_manager(monkeypatch)
    monkeypatch.setattr(main, 'manager', manager)
    final = tmp_path/'same.mp4'; final.write_bytes(b'finished')
    monkeypatch.setattr(main, '_probe_output_path', lambda req: (final,'',''))
    data = main.start_download(request(tmp_path))
    assert data['conflict'] and final.read_bytes() == b'finished' and not launches


@pytest.mark.parametrize('selection,expected', [(['137+140',['137','140']], '137+140'), (['m',[]], 'm')])
def test_actual_selection_is_saved_without_metadata_urls(tmp_path, monkeypatch, selection, expected):
    manager = ProcessManager()
    class Process:
        stdout = io.BytesIO(('__YTM_SELECTION__'+json.dumps(selection)+'\n').encode())
        def poll(self): return 0
        def wait(self): return 0
    manager._popen = lambda *a, **k: Process()
    job = DownloadJob('j', request(tmp_path), str(tmp_path/'same.%(ext)s'), attempt_id='a')
    manager.jobs[job.id] = job
    manager._run_attempt(job, ['yt-dlp'], 'a')
    assert job.resolved_format == expected
    stored = json.loads((tmp_path/'jobs.json').read_text())['jobs'][0]
    assert stored['resolved_format'] == expected


def test_stop_during_running_writer_keeps_reserve_until_exit(tmp_path, monkeypatch):
    manager, launches = held_manager(monkeypatch)
    job = manager.jobs[manager.start_download(request(tmp_path))]
    entered = threading.Event(); exit_allowed = threading.Event()
    def body(target):
        entered.set(); assert exit_allowed.wait(5)
        manager._finish(target, 'stopped', 'stopped')
    monkeypatch.setattr(manager, '_worker_body', body)
    thread = threading.Thread(target=manager._worker,args=(job,)); thread.start()
    try:
        assert entered.wait(3)
        assert manager.stop(job.id)
        assert job.worker_active and manager._reserved and job.cancel_event.is_set()
        with pytest.raises(DownloadConflict): manager.start_download(request(tmp_path))
    finally:
        exit_allowed.set(); thread.join(5)
    assert not thread.is_alive() and not manager._reserved and job.status == 'stopped'


def test_retry_finished_output_opens_file_conflict_without_overwriting(tmp_path, monkeypatch):
    import app.main as main
    manager, launches = held_manager(monkeypatch)
    monkeypatch.setattr(main, 'manager', manager)
    job = manager.jobs[manager.start_download(request(tmp_path))]; end(manager, job)
    output = tmp_path/'same.mp4'; output.write_bytes(b'finished')
    partial = tmp_path/'same.f137.mp4.part'; partial.write_bytes(b'partial')
    with pytest.raises(HTTPException) as conflict: main.retry_download(job.id)
    assert conflict.value.status_code == 409 and conflict.value.detail['code'] == 'output_exists'
    assert output.read_bytes() == b'finished' and partial.read_bytes() == b'partial' and len(launches) == 1


def test_manual_resume_opens_new_retry_budget_without_resetting_attempt(tmp_path, monkeypatch):
    import app.process_manager as module
    manager, launches = held_manager(monkeypatch)
    job = manager.jobs[manager.start_download(request(tmp_path, max_restarts=1))]
    job.attempt = 10; end(manager, job); manager.retry(job.id)
    calls = []
    monkeypatch.setattr(module, 'build_download_command', lambda *a: ['yt-dlp'])
    def attempt(target, argv, attempt_id):
        calls.append(target.attempt); target.diagnostic_tail.append('Read timed out'); return 1,''
    monkeypatch.setattr(manager, '_run_attempt', attempt)
    manager._wait = lambda event, seconds: job.retry_now.set()
    manager._worker(job)
    assert calls == [11,12] and job.attempt == 12 and not manager._reserved


@pytest.mark.parametrize('status', ['success','error','stopped','exception'])
def test_real_worker_finally_releases_every_terminal_run(tmp_path, monkeypatch, status):
    import app.process_manager as module
    manager, launches = held_manager(monkeypatch)
    job = manager.jobs[manager.start_download(request(tmp_path, auto_retry=False))]
    output = tmp_path/'same.mp4'; output.write_bytes(b'complete')
    if status == 'stopped': job.cancel_event.set()
    def build(*args):
        if status == 'exception': raise ValueError('bad argv')
        return ['yt-dlp']
    monkeypatch.setattr(module, 'build_download_command', build)
    monkeypatch.setattr(manager, '_run_attempt', lambda *a: (0,str(output)) if status == 'success' else (1,''))
    manager._worker(job)
    assert job.status == ('error' if status == 'exception' else status)
    assert not manager._reserved and not job.worker_active
    assert output.read_bytes() == b'complete'


def test_converted_audio_resume_keeps_downloaded_source_for_conversion(tmp_path, monkeypatch):
    manager, launches = held_manager(monkeypatch)
    req = request(tmp_path).model_copy(update={'download_mode':'audio','audio_format':'mp3','selected_format':''})
    job = manager.jobs[manager.start_download(req)]; job.attempt = 1; job.resolved_format = '140'; end(manager, job)
    source = tmp_path/'same.m4a'; source.write_bytes(b'source audio')
    assert manager.retry(job.id) and source.read_bytes() == b'source audio'
    assert len(launches) == 2
