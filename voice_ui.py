"""voice-tool web UI: an ElevenLabs-style page for generating voiceovers locally.

Start it with `make ui` (or `.venv/bin/python voice_ui.py`), then open http://127.0.0.1:7860
Options: --port 7861 (or UI_PORT=7861), --host 0.0.0.0 to reach it from other devices, --no-browser.
The model runs in a child process: Cancel kills it (memory freed at once), and it is unloaded after
VOICE_TOOL_UI_IDLE_MIN minutes without work (default 10).

Tags in the script:
  standard engine  tone tags such as [calm] [excited] change emotion/pace from that point on
  turbo engine     native tags such as [laugh] [sigh] [whispering] are passed to the model as written
  both             [pause] and [long pause] insert silence
"""
import argparse, multiprocessing as mp, os, queue, re, signal, socket, threading, time, uuid, webbrowser
from pathlib import Path
from urllib.parse import quote

import uvicorn
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import FileResponse, JSONResponse
from starlette.routing import Route

import voice_core as vc

UI_HTML = vc.BASE / "ui" / "index.html"
MAX_CHARS = 5000
OUTPUT_EXTS = (".wav", ".mp3")

# ── tags ──────────────────────────────────────────────────────────────────
# Standard engine: tone -> (emotion, pace). None keeps the slider value; [neutral] resets both to the sliders.
TONES = {
    "neutral": (None, None),
    "calm": (0.4, None),
    "serious": (0.45, None),
    "warm": (0.6, 0.45),
    "confident": (0.65, None),
    "happy": (0.7, 0.45),
    "excited": (0.85, 0.35),
    "dramatic": (1.0, 0.3),
}
# Turbo engine: tokens the Chatterbox Turbo tokenizer knows (added_tokens.json of ResembleAI/chatterbox-turbo).
TURBO_STYLES = ["narration", "advertisement", "happy", "surprised", "sarcastic",
                "angry", "fear", "crying", "dramatic", "whispering"]
TURBO_SOUNDS = ["laugh", "chuckle", "sigh", "gasp", "cough", "clear throat", "sniff", "groan", "shush"]
PAUSES = {"pause": 0.6, "long pause": 1.2}
TAG_RE = re.compile(r"\[([A-Za-z][A-Za-z ]{0,30})\]")
TONE_SWITCH_GAP = 0.2     # silence between two tone segments, same as between sentences
END_GAP = 0.35            # voice_core's default pause after a segment


def parse_script(text, engine="standard", emotion=0.55, pace=0.5):
    """Turn tagged text into voice_core segments. Returns (segments, warnings)."""
    turbo = engine == "turbo"
    turbo_tags = set(TURBO_STYLES) | set(TURBO_SOUNDS)
    segments, warnings, buf = [], {}, []
    cur = (emotion, pace)

    def flush(pause_after):
        t = " ".join("".join(buf).split())
        buf.clear()
        if t:
            segments.append({"text": t, "emotion": cur[0], "pace": cur[1], "pause_after": pause_after})
            return True
        return False

    pos = 0
    for m in TAG_RE.finditer(text):
        buf.append(text[pos:m.start()])
        pos = m.end()
        tag = " ".join(m.group(1).lower().split())
        if tag in PAUSES:
            if not flush(PAUSES[tag]) and segments:
                segments[-1]["pause_after"] += PAUSES[tag]
        elif turbo and tag in turbo_tags:
            buf.append(f" [{tag}] ")
        elif not turbo and tag in TONES:
            flush(TONE_SWITCH_GAP)
            e, p = TONES[tag]
            cur = (emotion if e is None else e, pace if p is None else p)
        elif turbo and tag in TONES:
            warnings[f"[{tag}] only works with the Standard model, removed"] = None
        elif not turbo and tag in turbo_tags:
            warnings[f"[{tag}] only works with the Turbo model, removed"] = None
        else:
            warnings[f"Unknown tag [{tag}] removed"] = None
    buf.append(text[pos:])
    flush(END_GAP)
    return segments, list(warnings)


# ── engine: the models live in a child process ───────────────────────────
# A generation inside PyTorch can't be interrupted from a thread, so the models run in their own
# process. Cancel = kill that process: the generation stops at once and all its memory is returned.
# It is also stopped after IDLE_UNLOAD_S without work, and restarted (model reload) on the next job.
IDLE_UNLOAD_S = float(os.environ.get("VOICE_TOOL_UI_IDLE_MIN") or 10) * 60
FINISHED = ("done", "error", "cancelled")


def _free_device_cache():
    try:
        import torch
        if torch.backends.mps.is_available():
            torch.mps.empty_cache()
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
    except Exception:
        pass


def _engine_main(conn):
    """Child process: receives (segments, opts), sends ("progress", done, total) then ("done", result) or ("error", msg)."""
    import gc
    signal.signal(signal.SIGINT, signal.SIG_IGN)        # Ctrl+C is handled by the server, which stops us
    while True:
        try:
            segments, opts = conn.recv()
        except (EOFError, OSError):
            return                                       # server went away
        try:
            r = vc.synthesize(segments, progress=lambda d, t: conn.send(("progress", d, t)), **opts)
            msg = ("done", r)
        except Exception as e:
            vc.log.exception("UI generation failed")
            msg = ("error", str(e) or e.__class__.__name__)
        gc.collect()
        _free_device_cache()
        try:
            conn.send(msg)
        except OSError:
            return


class _Engine:
    def __init__(self):
        self.proc = self.conn = None
        self._stop_lock = threading.Lock()
        self.loaded = set()                              # engines ("standard"/"turbo") loaded in the process

    def alive(self):
        return self.proc is not None and self.proc.is_alive()

    def start(self):
        ctx = mp.get_context("spawn")
        self.conn, child = ctx.Pipe()
        self.proc = ctx.Process(target=_engine_main, args=(child,), daemon=True, name="voice-tool-engine")
        self.proc.start()
        child.close()
        self.loaded = set()

    def stop(self):                                      # called by the worker thread and at shutdown
        with self._stop_lock:
            proc, conn, self.proc, self.conn, self.loaded = self.proc, self.conn, None, None, set()
        if proc is not None:
            if proc.is_alive():
                proc.kill()
            proc.join(10)
            conn.close()


# ── jobs: one worker thread feeds the engine, one generation at a time ───
_jobs, _jobs_lock, _queue, _engine = {}, threading.Lock(), queue.Queue(), _Engine()


def _set(job_id, **fields):
    with _jobs_lock:
        if job_id in _jobs:
            _jobs[job_id].update(fields)


def _cancel_requested(job_id):
    with _jobs_lock:
        return _jobs.get(job_id, {}).get("cancel", True)


def _worker():
    while True:
        try:
            job_id, segments, opts = _queue.get(timeout=IDLE_UNLOAD_S if _engine.alive() else None)
        except queue.Empty:
            vc.log.info("UI idle for %.0f min, unloading the model", IDLE_UNLOAD_S / 60)
            _engine.stop()
            continue
        with _jobs_lock:                                 # skip jobs cancelled while they were queued
            j = _jobs.get(job_id)
            if not j or j["cancel"]:
                continue
            warm = _engine.alive() and opts["engine"] in _engine.loaded
            j.update(status="generating" if warm else "loading", started=time.time())
        try:
            _run(job_id, segments, opts)
        except Exception as e:                           # never let the worker thread die
            vc.log.exception("UI job %s failed", job_id)
            _engine.stop()
            _set(job_id, status="error", error=str(e) or e.__class__.__name__)


def _run(job_id, segments, opts):
    if not _engine.alive():
        _engine.start()
    proc, conn = _engine.proc, _engine.conn            # local refs: a concurrent stop() just closes them
    conn.send((segments, opts))
    while True:
        if _cancel_requested(job_id):
            _engine.stop()
            vc.log.info("UI job %s cancelled, engine process stopped", job_id)
            _set(job_id, status="cancelled")
            return
        try:
            if not conn.poll(0.2):
                if not proc.is_alive():
                    raise EOFError
                continue
            msg = conn.recv()
        except (EOFError, OSError):
            code = proc.exitcode
            _engine.stop()
            _set(job_id, status="error", error=f"The voice engine stopped unexpectedly (exit code {code}). "
                                               "It may have run out of memory: close other apps and try again.")
            return
        if msg[0] == "progress":
            _set(job_id, status="generating", done=msg[1], total=msg[2])
            continue
        if msg[0] == "done":
            _engine.loaded.add(opts["engine"])
            r = msg[1]
            _set(job_id, status="done", result={**_file_info(Path(r["path"])), "duration_s": r["duration_s"],
                                                "took_s": r["took_s"], "note": r["note"]})
        else:
            _set(job_id, status="error", error=msg[1])
        return


def _prune_jobs(keep=50):
    with _jobs_lock:
        finished = [k for k, j in _jobs.items() if j["status"] in FINISHED]
        for k in finished[:-keep]:
            del _jobs[k]


# ── helpers ──────────────────────────────────────────────────────────────

def _file_info(p):
    st = p.stat()
    return {"name": p.name, "url": f"/media/out/{quote(p.name)}", "size": st.st_size, "mtime": st.st_mtime}


def _pretty(stem):
    return " ".join(w.capitalize() for w in re.split(r"[_\-\s]+", stem) if w) or stem


def _default_voice(files):
    try:
        name = vc.voice_path("").name
        return name if name in files else (files[0] if files else "")
    except FileNotFoundError:
        return files[0] if files else ""


def _auto_name(voice, text):
    words = re.findall(r"[A-Za-z0-9]+", TAG_RE.sub(" ", text))[:5]
    return f"{Path(voice).stem}_{'_'.join(words).lower() or 'voiceover'}"[:60]


def _num(v, default, lo, hi):
    try:
        return max(lo, min(float(v), hi))
    except (TypeError, ValueError):
        return default


def _err(msg, code=400):
    return JSONResponse({"error": msg}, status_code=code)


# ── routes ───────────────────────────────────────────────────────────────

async def index(request: Request):
    return FileResponse(UI_HTML, headers={"Cache-Control": "no-cache"})


async def config(request: Request):
    files = vc.list_voice_files()
    with _jobs_lock:                                     # lets a reloaded page pick up a running generation
        active = next((k for k, j in _jobs.items() if j["status"] not in FINISHED), None)
    return JSONResponse({
        "active_job": active,
        "voices": [{"file": f, "name": _pretty(Path(f).stem), "url": f"/media/voices/{quote(f)}"} for f in files],
        "default_voice": _default_voice(files),
        "voices_dir": str(vc.VOICES_DIR),
        "max_chars": MAX_CHARS,
        "tags": {"tones": list(TONES), "styles": TURBO_STYLES, "sounds": TURBO_SOUNDS, "pauses": list(PAUSES)},
    })


async def history(request: Request):
    items = []
    for p in vc.DEFAULT_OUT.iterdir():
        if p.suffix.lower() in OUTPUT_EXTS and p.is_file():
            try:
                items.append(_file_info(p))
            except OSError:                             # deleted while listing
                pass
    items.sort(key=lambda i: i["mtime"], reverse=True)
    return JSONResponse(items[:50])


async def generate(request: Request):
    try:
        body = await request.json()
    except ValueError:
        return _err("Invalid JSON")
    if not isinstance(body, dict):
        return _err("Invalid request")
    text = str(body.get("text") or "")
    if len(text) > MAX_CHARS:
        return _err(f"Text is too long ({len(text)} characters, max {MAX_CHARS}).")
    engine = body.get("engine") if body.get("engine") in ("standard", "turbo") else "standard"
    voice = str(body.get("voice") or "")
    if voice not in vc.list_voice_files():
        return _err(f"Voice '{voice}' not found in {vc.VOICES_DIR}.")
    emotion = _num(body.get("emotion"), 0.55, 0.25, 2.0)
    pace = _num(body.get("pace"), 0.5, 0.0, 1.0)
    segments, warnings = parse_script(text, engine, emotion, pace)
    if not segments:
        return _err("Nothing to speak. Type some text first.")
    try:
        seed = max(0, min(int(body.get("seed") or 0), 2**31 - 1))
    except (TypeError, ValueError):
        seed = 0
    opts = {"engine": engine, "voice": voice, "fmt": "wav" if body.get("format") == "wav" else "mp3",
            "pace": pace, "seed": seed, "default_emotion": emotion, "filename": _auto_name(voice, text)}
    job_id = uuid.uuid4().hex[:12]
    with _jobs_lock:
        _jobs[job_id] = {"id": job_id, "status": "queued", "done": 0, "total": 0, "started": None,
                         "result": None, "error": None, "warnings": warnings, "cancel": False}
    _prune_jobs()
    _queue.put((job_id, segments, opts))
    return JSONResponse({"id": job_id, "warnings": warnings})


async def job(request: Request):
    with _jobs_lock:
        j = _jobs.get(request.path_params["job_id"])
        j = dict(j) if j else None
    if not j:
        return _err("Job not found", 404)
    j["elapsed"] = round(time.time() - j["started"], 1) if j["started"] else 0
    return JSONResponse(j)


async def cancel(request: Request):
    with _jobs_lock:
        j = _jobs.get(request.path_params["job_id"])
        if not j:
            return _err("Job not found", 404)
        if j["status"] not in FINISHED:
            j["cancel"] = True
            if j["status"] == "queued":
                j["status"] = "cancelled"
        status = j["status"]
    return JSONResponse({"status": status})


async def media(request: Request):
    base = {"voices": vc.VOICES_DIR, "out": vc.DEFAULT_OUT}.get(request.path_params["kind"])
    if base is None:
        return _err("Not found", 404)
    base = base.resolve()
    p = (base / request.path_params["name"]).resolve()
    if p.parent != base or not p.is_file():             # no path traversal, files directly in the folder only
        return _err("Not found", 404)
    return FileResponse(p)


app = Starlette(routes=[
    Route("/", index),
    Route("/api/config", config),
    Route("/api/history", history),
    Route("/api/generate", generate, methods=["POST"]),
    Route("/api/jobs/{job_id}", job),
    Route("/api/jobs/{job_id}/cancel", cancel, methods=["POST"]),
    Route("/media/{kind}/{name}", media),
])


def _port_free(host, port):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        try:
            s.bind((host, port))
            return True
        except OSError:
            return False


def main():
    ap = argparse.ArgumentParser(description="voice-tool web UI")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=int(os.environ.get("UI_PORT") or 7860))
    ap.add_argument("--no-browser", action="store_true")
    a = ap.parse_args()
    if not _port_free(a.host, a.port):
        raise SystemExit(f"Port {a.port} is already in use (is the UI already running?). "
                         f"Try another one: make ui UI_PORT={a.port + 1}")
    url = f"http://{'127.0.0.1' if a.host in ('0.0.0.0', '') else a.host}:{a.port}"
    threading.Thread(target=_worker, daemon=True).start()
    if not a.no_browser:
        threading.Timer(1.0, webbrowser.open, args=(url,)).start()
    print(f"\nvoice-tool UI running at {url}  (Ctrl+C to stop)\n", flush=True)
    try:
        uvicorn.run(app, host=a.host, port=a.port, log_level="warning")
    finally:
        _engine.stop()                                   # never leave a model process behind


if __name__ == "__main__":
    main()
