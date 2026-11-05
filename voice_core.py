"""Core synthesis for voice-tool: Chatterbox (Resemble AI, MIT licence) running locally.

Runs on NVIDIA GPUs (CUDA), Apple Silicon (MPS) or plain CPU.
Used by both the MCP server (voice_mcp.py) and the CLI (speak.py).
"""
import os, re, sys, time, threading, contextlib, logging, shutil, subprocess
from pathlib import Path

BASE = Path(__file__).resolve().parent
os.environ.setdefault("HF_HOME", str(BASE / ".models"))          # keep model weights inside voice-tool
os.environ.setdefault("PYTORCH_ENABLE_MPS_FALLBACK", "1")
os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")

VOICES_DIR = BASE / "voices"
DEFAULT_OUT = BASE / "VoiceOvers"
LOG_DIR = BASE / "logs"
DEFAULT_VOICE = os.environ.get("VOICE_TOOL_DEFAULT_VOICE", "my_voice")
AUDIO_EXTS = (".wav", ".flac", ".mp3", ".m4a", ".aiff", ".ogg")
for _d in (VOICES_DIR, DEFAULT_OUT, LOG_DIR):
    _d.mkdir(parents=True, exist_ok=True)

logging.basicConfig(filename=str(LOG_DIR / "voice-tool.log"), level=logging.INFO, encoding="utf-8",
                    format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("voice-tool")

_lock = threading.RLock()
_models = {}
_conds = {}   # engine -> (voice path, mtime) currently loaded as conditionals


def device():
    """cuda > mps > cpu. Override with VOICE_TOOL_DEVICE=cuda|mps|cpu."""
    forced = os.environ.get("VOICE_TOOL_DEVICE", "").strip().lower()
    if forced:
        return forced
    import torch
    if torch.cuda.is_available():
        return "cuda"
    mps = getattr(torch.backends, "mps", None)
    if mps is not None and mps.is_available():
        return "mps"
    return "cpu"


class _NoWatermark:
    """Pass-through replacement for Chatterbox's Perth watermarker: returns the audio unchanged."""
    def apply_watermark(self, wav, watermark=None, sample_rate=44100, **kwargs):
        return wav

    def get_watermark(self, *args, **kwargs):
        return None


def _disable_watermark():
    # Set VOICE_TOOL_WATERMARK=1 to keep Resemble's Perth watermark.
    if os.environ.get("VOICE_TOOL_WATERMARK", "0") == "1":
        return
    import perth
    perth.PerthImplicitWatermarker = _NoWatermark


def load_model(engine="standard"):
    engine = (engine or "standard").lower()
    with _lock:
        if engine not in _models:
            t = time.time()
            _disable_watermark()
            with contextlib.redirect_stdout(sys.stderr):
                if engine == "turbo":
                    from chatterbox.tts_turbo import ChatterboxTurboTTS as M
                elif engine == "standard":
                    from chatterbox.tts import ChatterboxTTS as M
                else:
                    raise ValueError("engine must be 'standard' or 'turbo'")
                _models[engine] = M.from_pretrained(device=device())
            log.info("loaded %s on %s in %.1fs", engine, device(), time.time() - t)
        return _models[engine]


def find_ffmpeg():
    """System ffmpeg if present, otherwise the copy bundled with the imageio-ffmpeg package."""
    for c in (shutil.which("ffmpeg"), "/opt/homebrew/bin/ffmpeg", "/usr/local/bin/ffmpeg"):
        if c and os.path.exists(c):
            return c
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        return None


def voice_path(voice=""):
    v = (voice or DEFAULT_VOICE).strip()
    p = Path(os.path.expanduser(v))
    if not p.is_absolute():
        p = VOICES_DIR / v
    if not p.exists() or not p.suffix:   # my_voice -> my_voice.wav / .mp3 / ...
        p = p.with_suffix("") if p.suffix.lower() in AUDIO_EXTS else p
        for ext in AUDIO_EXTS:
            if p.with_suffix(ext).exists():
                p = p.with_suffix(ext)
                break
    if not p.exists():
        raise FileNotFoundError(
            f"Voice sample not found: {p}. Put a clean 10-30 s recording in {VOICES_DIR} "
            f"(e.g. my_voice.wav) or pass voice=<file name>. Available: {list_voice_files() or 'none'}")
    return p


def list_voice_files():
    return sorted(p.name for p in VOICES_DIR.iterdir() if p.suffix.lower() in AUDIO_EXTS)


def chunk_text(text, max_chars=280):
    text = re.sub(r"\s+", " ", text.strip())
    sentences = re.split(r"(?<=[.!?…])\s+", text)
    parts = []
    for s in sentences:
        while len(s) > max_chars:                       # split very long sentences at a comma/space
            cut = max(s.rfind(", ", 0, max_chars), s.rfind(" ", 0, max_chars))
            cut = cut if cut > 40 else max_chars
            parts.append(s[:cut + 1].strip()); s = s[cut + 1:].strip()
        if s:
            parts.append(s)
    chunks, cur = [], ""
    for s in parts:
        if cur and len(cur) + len(s) + 1 > max_chars:
            chunks.append(cur); cur = s
        else:
            cur = f"{cur} {s}".strip()
    if cur:
        chunks.append(cur)
    return chunks


def _prepare(model, engine, vp, emotion):
    key = (str(vp), vp.stat().st_mtime)
    if _conds.get(engine) != key:
        with contextlib.redirect_stdout(sys.stderr):
            model.prepare_conditionals(str(vp), exaggeration=emotion)
        _conds[engine] = key


def _out_path(output_dir, filename, ext):
    out_dir = Path(os.path.expanduser(output_dir)) if output_dir else DEFAULT_OUT
    if not out_dir.is_absolute():
        out_dir = BASE / out_dir
    out_dir.mkdir(parents=True, exist_ok=True)
    name = re.sub(r"[^\w\-. ]+", "_", (filename or "").strip()).strip(" .") or f"vo_{time.strftime('%Y%m%d_%H%M%S')}"
    name = re.sub(r"\.(wav|mp3)$", "", name, flags=re.I)
    p, i = out_dir / f"{name}.{ext}", 2
    while p.exists():
        p = out_dir / f"{name}_{i}.{ext}"; i += 1
    return p


def synthesize(segments, engine="standard", voice="", output_dir="", filename="",
               fmt="wav", pace=0.5, seed=0, default_emotion=0.5, gap=0.2, progress=None):
    """segments: list of dicts {text, emotion?, pace?, pause_after?}. Returns a result dict.
    progress: optional callback(done_chunks, total_chunks), called once the model is ready and after each chunk."""
    import torch, torchaudio
    engine = (engine or "standard").lower()
    fmt = (fmt or "wav").lower().lstrip(".")
    vp = voice_path(voice)
    t0 = time.time()
    with _lock:
        model = load_model(engine)
        sr = model.sr
        pieces = []
        if seed:
            torch.manual_seed(int(seed))
        total = sum(len(chunk_text(seg.get("text") or "")) for seg in segments if (seg.get("text") or "").strip())
        done = 0
        if progress:
            progress(done, total)
        for seg in segments:
            text = (seg.get("text") or "").strip()
            if not text:
                continue
            emotion = float(seg.get("emotion", default_emotion))
            emotion = max(0.25, min(emotion, 2.0))
            _prepare(model, engine, vp, emotion)
            chunks = chunk_text(text)
            for i, chunk in enumerate(chunks):
                with contextlib.redirect_stdout(sys.stderr):
                    if engine == "turbo":
                        wav = model.generate(chunk)
                    else:
                        wav = model.generate(chunk, exaggeration=emotion, cfg_weight=float(seg.get("pace", pace)))
                pieces.append(wav.detach().cpu().float())
                done += 1
                if progress:
                    progress(done, total)
                last = i == len(chunks) - 1
                pause = float(seg.get("pause_after", 0.35)) if last else gap
                if pause > 0:
                    pieces.append(torch.zeros(1, int(sr * pause)))
        if not pieces:
            raise ValueError("No text to speak.")
        while pieces and pieces[-1].abs().max() == 0:
            pieces.pop()
        audio = torch.cat(pieces, dim=-1)
    peak = float(audio.abs().max())
    if peak > 0.99:
        audio = audio * (0.98 / peak)
    wav_path = _out_path(output_dir, filename, "wav")
    torchaudio.save(str(wav_path), audio, sr)
    final, note = wav_path, ""
    if fmt == "mp3":
        ff = find_ffmpeg()
        if ff:
            mp3 = wav_path.with_suffix(".mp3")
            subprocess.run([ff, "-y", "-loglevel", "error", "-i", str(wav_path), "-codec:a", "libmp3lame",
                            "-b:a", "192k", str(mp3)], check=True)
            wav_path.unlink(missing_ok=True)
            final = mp3
        else:
            note = "ffmpeg not found, saved WAV instead."
    dur = audio.shape[-1] / sr
    took = time.time() - t0
    log.info("generated %s (%.1fs audio in %.1fs, engine=%s, voice=%s, device=%s)",
             final, dur, took, engine, vp.name, device())
    return {"path": str(final), "duration_s": round(dur, 2), "took_s": round(took, 1),
            "engine": engine, "voice": vp.name, "note": note}
