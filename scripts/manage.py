#!/usr/bin/env python3
"""voice-tool manager. Standard library only, so it runs before anything is installed.

Usually called through `make <target>` (or scripts/bootstrap.sh / scripts/bootstrap.ps1).

Commands:
  setup       install + models + register (the one-shot first-time setup)
  install     create .venv (Python 3.11) and install torch + Chatterbox for this machine
  models      download the model weights and render a test clip
  test        render a test clip with your own voice sample (voices/my_voice.*)
  register    add the voice-tool MCP server to Claude Desktop (and Claude Code if installed)
  unregister  remove it again
  doctor      show what this machine will use (OS, GPU, Python, voices, ffmpeg)
  speak       generate from the terminal: speak "Text" [--emotion 0.7 --mp3 ...]
  ui          start the web UI (ElevenLabs-style) at http://127.0.0.1:7860
  clean       delete .venv (keeps models and voices)
  clean-all   delete .venv and the downloaded models

Environment overrides:
  TORCH=auto|default|cpu|cu118|cu121|cu124   which PyTorch build to install (default auto)
  SKIP_MODELS=1                             setup without downloading the models
  VOICE_TOOL_DEVICE=cuda|mps|cpu            force the device at runtime
  UI_PORT=7861                              port for the web UI (default 7860)
"""
import json, os, platform, shutil, subprocess, sys, time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
VENV = ROOT / ".venv"
IS_WIN = os.name == "nt"
PY = VENV / ("Scripts/python.exe" if IS_WIN else "bin/python")
SERVER = ROOT / "voice_mcp.py"
NAME = "voice-tool"
PY_VERSION = "3.11"
TORCH_VERSION = "2.6.0"
CUDA_BUILDS = ("cu118", "cu124", "cu126")


def say(msg):
    print(f"\n==> {msg}", flush=True)


def run(cmd, **kw):
    cmd = [str(c) for c in cmd]
    print("+ " + " ".join(cmd), flush=True)
    subprocess.run(cmd, check=True, **kw)


def uv():
    cands = [os.environ.get("UV"), shutil.which("uv")]
    home = Path.home()
    for d in (home / ".local" / "bin", home / ".cargo" / "bin"):
        cands += [str(d / "uv"), str(d / "uv.exe")]
    for c in cands:
        if c and Path(c).exists():
            return c
    sys.exit("uv not found. Run `make setup` (it installs uv) or see https://docs.astral.sh/uv/")


def has_nvidia():
    if not shutil.which("nvidia-smi"):
        return False
    try:
        subprocess.run(["nvidia-smi"], capture_output=True, check=True, timeout=20)
        return True
    except Exception:
        return False


def torch_build():
    choice = os.environ.get("TORCH", "auto").strip().lower()
    if choice != "auto":
        return choice
    if sys.platform == "darwin":
        return "default"            # PyPI wheels include Apple Silicon (MPS) support
    if has_nvidia():
        return "cu124"
    return "cpu"


def env_for_runtime():
    e = dict(os.environ)
    e.setdefault("HF_HOME", str(ROOT / ".models"))
    e.setdefault("PYTORCH_ENABLE_MPS_FALLBACK", "1")
    e.setdefault("PYTHONIOENCODING", "utf-8")
    return e


# ── commands ──────────────────────────────────────────────────────────────

def cmd_install():
    say(f"Python {PY_VERSION} virtual environment (.venv)")
    if not PY.exists():
        run([uv(), "venv", "--python", PY_VERSION, VENV])
    base = [uv(), "pip", "install", "--python", PY]
    build = torch_build()
    say(f"PyTorch {TORCH_VERSION} ({build} build)")
    if build == "cpu" or build in CUDA_BUILDS:
        run(base + [f"torch=={TORCH_VERSION}", f"torchaudio=={TORCH_VERSION}",
                    "--index-url", f"https://download.pytorch.org/whl/{build}"])
    else:
        run(base + [f"torch=={TORCH_VERSION}", f"torchaudio=={TORCH_VERSION}"])
    say("Chatterbox + MCP server dependencies")
    run(base + ["-r", ROOT / "requirements.txt"])
    run([PY, "-c", "import torch, chatterbox, mcp; "
                   "print('torch', torch.__version__, '| cuda', torch.cuda.is_available(), "
                   "'| mps', torch.backends.mps.is_available())"])


def _need_venv():
    if not PY.exists():
        sys.exit("Not installed yet. Run `make setup` (or `make install`) first.")


def cmd_models():
    _need_venv()
    say("Downloading models (about 4 GB the first time) + test clip with the built-in voice")
    code = r"""
import time, voice_core as vc, torchaudio
print("device:", vc.device())
t = time.time(); m = vc.load_model("standard"); print(f"standard model ready in {time.time()-t:.0f}s")
t = time.time(); wav = m.generate("Voice tool is set up and ready.")
out = vc.DEFAULT_OUT / "_setup_test_builtin_voice.wav"; torchaudio.save(str(out), wav, m.sr)
print(f"test clip in {time.time()-t:.0f}s -> {out}")
del vc._models["standard"]
t = time.time(); vc.load_model("turbo"); print(f"turbo model ready in {time.time()-t:.0f}s")
"""
    run([PY, "-c", code], cwd=ROOT, env=env_for_runtime())


def cmd_test():
    _need_venv()
    code = r"""
import voice_core as vc
v = vc.list_voice_files()
if not v:
    raise SystemExit(f"No voice sample in {vc.VOICES_DIR}. Add a clean 10-30 s recording, e.g. my_voice.wav")
try:
    vp = vc.voice_path("")
except FileNotFoundError:
    vp = vc.VOICES_DIR / v[0]
print("voice sample:", vp.name, "| device:", vc.device())
r = vc.synthesize([{"text": "Hey! This is my cloned voice, generated locally, for free.", "emotion": 0.6}],
                  voice=str(vp), filename="_test_my_voice", fmt="mp3", pace=0.4)
print("saved", r["path"], f"({r['duration_s']}s audio in {r['took_s']}s)", r["note"])
"""
    run([PY, "-c", code], cwd=ROOT, env=env_for_runtime())


def claude_desktop_config():
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "Claude" / "claude_desktop_config.json"
    if IS_WIN:
        return Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming")) / "Claude" / "claude_desktop_config.json"
    return Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "Claude" / "claude_desktop_config.json"


def _server_entry():
    return {"command": str(PY), "args": [str(SERVER)],
            "env": {"PYTORCH_ENABLE_MPS_FALLBACK": "1", "HF_HOME": str(ROOT / ".models"),
                    "PYTHONIOENCODING": "utf-8"}}


def _edit_config(fn):
    cfg = claude_desktop_config()
    data = {}
    if cfg.exists() and cfg.stat().st_size > 0:
        data = json.loads(cfg.read_text(encoding="utf-8"))
        shutil.copy2(cfg, cfg.with_name(cfg.name + f".bak-{time.strftime('%Y%m%d%H%M%S')}"))
    fn(data)
    cfg.parent.mkdir(parents=True, exist_ok=True)
    cfg.write_text(json.dumps(data, indent=2), encoding="utf-8")
    return cfg


def cmd_register():
    _need_venv()
    say("Registering the MCP server")
    cfg = _edit_config(lambda d: d.setdefault("mcpServers", {}).__setitem__(NAME, _server_entry()))
    print(f"Claude Desktop: {cfg}")
    claude = shutil.which("claude")
    if claude:
        subprocess.run([claude, "mcp", "remove", "-s", "user", NAME], capture_output=True)
        e = _server_entry()["env"]
        run([claude, "mcp", "add", "-s", "user", NAME,
             "-e", f"PYTORCH_ENABLE_MPS_FALLBACK={e['PYTORCH_ENABLE_MPS_FALLBACK']}",
             "-e", f"HF_HOME={e['HF_HOME']}", "-e", "PYTHONIOENCODING=utf-8",
             "--", PY, SERVER])
        print("Claude Code: added (user scope)")
    print("Restart the Claude app to load the voice-tool tools.")


def cmd_unregister():
    cfg = _edit_config(lambda d: d.get("mcpServers", {}).pop(NAME, None))
    print(f"Removed {NAME} from {cfg}")
    if shutil.which("claude"):
        subprocess.run([shutil.which("claude"), "mcp", "remove", "-s", "user", NAME])


def cmd_doctor():
    say("voice-tool doctor")
    print(f"OS:            {platform.system()} {platform.release()} ({platform.machine()})")
    print(f"Folder:        {ROOT}")
    print(f"uv:            {shutil.which('uv') or os.environ.get('UV') or 'not found'}")
    print(f"NVIDIA GPU:    {'yes' if has_nvidia() else 'no'}")
    print(f"Torch build:   {torch_build()} (TORCH={os.environ.get('TORCH', 'auto')})")
    print(f"Installed:     {'yes' if PY.exists() else 'no (run make setup)'}")
    models = ROOT / ".models"
    size = sum(f.stat().st_size for f in models.rglob("*") if f.is_file()) / 1e9 if models.exists() else 0
    print(f"Models:        {size:.1f} GB in .models")
    voices = sorted(p.name for p in (ROOT / "voices").glob("*") if p.suffix.lower() in
                    (".wav", ".flac", ".mp3", ".m4a", ".aiff", ".ogg"))
    print(f"Voice samples: {voices or 'none (add voices/my_voice.wav)'}")
    print(f"Claude config: {claude_desktop_config()}")
    if PY.exists():
        subprocess.run([str(PY), "-c", "import voice_core as vc; print('Device:       ', vc.device()); "
                                       "print('ffmpeg:       ', vc.find_ffmpeg() or 'missing')"],
                       cwd=ROOT, env=env_for_runtime())


def cmd_speak(args):
    _need_venv()
    if not args:
        sys.exit('usage: make speak TEXT="Hello there" ARGS="--emotion 0.7 --mp3"')
    run([PY, ROOT / "speak.py", *args], cwd=ROOT, env=env_for_runtime())


def cmd_ui():
    _need_venv()
    say("Starting the voice-tool web UI (Ctrl+C to stop)")
    try:
        run([PY, ROOT / "voice_ui.py"], cwd=ROOT, env=env_for_runtime())
    except KeyboardInterrupt:
        print("\nUI stopped.")


def cmd_clean(all_=False):
    if VENV.exists():
        shutil.rmtree(VENV); print("removed .venv")
    if all_ and (ROOT / ".models").exists():
        shutil.rmtree(ROOT / ".models"); print("removed .models")


def cmd_setup():
    cmd_install()
    if os.environ.get("SKIP_MODELS") == "1":
        say("Skipping model download (SKIP_MODELS=1)")
    else:
        cmd_models()
    cmd_register()
    say("Done")
    print("1. Put a clean 10-30 s recording of the voice in voices/ (e.g. voices/my_voice.wav)")
    print("2. make test            -> renders VoiceOvers/_test_my_voice.mp3")
    print("3. Restart Claude and ask: 'generate a voiceover in my voice: ...'")
    print("4. make ui              -> web UI in your browser")


def main():
    if len(sys.argv) < 2 or sys.argv[1] in ("-h", "--help", "help"):
        print(__doc__); return
    cmd, args = sys.argv[1], [a for a in sys.argv[2:] if a.strip()]
    table = {"setup": cmd_setup, "install": cmd_install, "models": cmd_models, "test": cmd_test,
             "register": cmd_register, "unregister": cmd_unregister, "doctor": cmd_doctor,
             "clean": cmd_clean, "clean-all": lambda: cmd_clean(True), "speak": lambda: cmd_speak(args),
             "ui": cmd_ui}
    if cmd not in table:
        sys.exit(f"unknown command {cmd!r}. Try: {', '.join(table)}")
    try:
        table[cmd]()
    except subprocess.CalledProcessError as e:
        sys.exit(f"\nFailed: {' '.join(map(str, e.cmd))} (exit {e.returncode})")


if __name__ == "__main__":
    main()
