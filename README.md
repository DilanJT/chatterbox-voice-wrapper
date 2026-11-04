# voice-tool

Free, local, ElevenLabs-style voiceovers in a cloned voice, plus an MCP server so Claude can generate them for you.

- Engine: [Chatterbox](https://github.com/resemble-ai/chatterbox) by Resemble AI (MIT licence, commercial use OK)
- Runs on **macOS** (Apple Silicon GPU), **Windows** and **Linux** (NVIDIA GPU via CUDA, or CPU)
- Two engines: `standard` (emotion and pace control) and `turbo` (faster, understands `[laugh]` `[chuckle]` `[sigh]` …)
- Voice cloning from a 10–30 s sample, with no training step

## Quick start

```bash
git clone <your-repo-url> voice-tool
cd voice-tool
make setup
```

`make setup` does everything:

1. installs [uv](https://docs.astral.sh/uv/) if it's missing (it also provides Python 3.11, so no system Python is needed)
2. creates `.venv` and installs the right PyTorch build for the machine (Apple Silicon / CUDA 12.4 / CPU)
3. downloads the model weights (~4 GB) into `.models/` and renders a test clip
4. registers the `voice-tool` MCP server with Claude Desktop (and Claude Code if it's installed)

Then:

1. Put a clean 10–30 s recording in `voices/`, e.g. `voices/my_voice.wav` (see [voices/README.md](voices/README.md))
2. `make test` renders `VoiceOvers/_test_my_voice.mp3`
3. Restart the Claude app and ask: *"Generate a voiceover in my voice: …"*

### Per OS

| OS | Needs | Run |
|---|---|---|
| macOS | Xcode command line tools (for `make`): `xcode-select --install` | `make setup` (or double-click `Setup voice-tool.command`) |
| Linux | `make`, `curl` | `make setup` |
| Windows | `make`: `winget install ezwinports.make` (or Git Bash) | `make setup` |
| Windows, no make | nothing | double-click `setup.bat`, or `powershell -ExecutionPolicy Bypass -File scripts\bootstrap.ps1 setup` |

An NVIDIA GPU is detected automatically (`nvidia-smi`). To force a build: `make setup TORCH=cpu` or `make setup TORCH=cu124`.

## Commands

| Command | What it does |
|---|---|
| `make setup` | First-time setup: install + models + register |
| `make install` | Create `.venv` and install packages only |
| `make models` | Download the weights and render a test clip with the built-in voice |
| `make test` | Render a test clip with your sample in `voices/` |
| `make register` / `make unregister` | Add or remove the MCP server in Claude |
| `make doctor` | Show OS, GPU, device, voices, ffmpeg, Claude config path |
| `make speak TEXT="Hello there" ARGS="--emotion 0.7 --mp3"` | Generate from the terminal |
| `make clean` / `make clean-all` | Delete `.venv` / also delete the models |

On Windows without make, swap `make <cmd>` for `setup.bat <cmd>`.

## Using it from Claude (MCP tools)

| Tool | Use |
|---|---|
| `generate_voiceover` | One clip: `text`, `emotion`, `pace`, `engine`, `voice`, `output_dir`, `filename`, `format` (wav/mp3), `seed` |
| `generate_voiceover_segments` | One file whose emotion changes per section, e.g. hook / body / CTA |
| `list_voices`, `list_voiceovers`, `voice_tool_status` | Housekeeping |

Example prompt:

> Generate a voiceover in my voice as one mp3: hook at emotion 0.8, body 0.55, CTA 0.7. Save it as promo_v1 to ~/Desktop.
> "Stop scrolling. … "

Output goes to `VoiceOvers/` unless you give a folder. Files are never overwritten (`_2`, `_3` …).

## Getting a natural read

| Setting | Effect |
|---|---|
| `emotion` 0.55–0.65 | Natural narration. Below ~0.45 tends to sound flat or robotic; 0.75–0.9 is excited |
| `pace` 0.3 | Slower and more expressive; pair it with higher emotion |
| Punctuation | Commas and `...` create real pauses. Spell out numbers/acronyms (`ten-thirty P.M.`, `V.I.P.`) |
| `engine="turbo"` | Faster; supports `[laugh] [chuckle] [sigh] [cough] [gasp]`; no emotion dial |
| `seed` | The same number gives the same take; 0 gives a new take each time |
| Script tags | ElevenLabs-style tags (`[excited]`, `[warmly]`) aren't read. Map them to per-segment `emotion` |

Speeding audio up afterwards (atempo) can make it sound mechanical. Prefer re-generating with a tighter script.

## Configuration (environment variables)

| Variable | Default | Meaning |
|---|---|---|
| `VOICE_TOOL_DEFAULT_VOICE` | `my_voice` | Default sample in `voices/` (any extension) |
| `VOICE_TOOL_DEVICE` | auto | Force `cuda`, `mps` or `cpu` |
| `VOICE_TOOL_WATERMARK` | `0` | `1` keeps Resemble's inaudible Perth watermark (off by default) |
| `VOICE_TOOL_PRELOAD` | `0` | `1` loads the model when the MCP server starts |
| `HF_HOME` | `.models/` | Where model weights are stored |

## Notes and troubleshooting

- **Speed:** the standard engine on an M4 Mac mini takes roughly 3–4 s per second of audio when nothing else is loaded; turbo is about 2–3× faster. An NVIDIA GPU is much faster.
- **Memory:** every Claude client that starts the MCP server loads its own copy of the model (~3–4 GB). Close the clients you don't use.
- **"Did not respond within 60s" in Claude:** long scripts can take longer than the client waits. The file still finishes in `VoiceOvers/`; ask Claude to `list_voiceovers`.
- **Model download blocked:** the weights come from huggingface.co. On restricted networks, copy an existing `.models/` folder from another machine.
- **Windows CUDA:** needs an NVIDIA driver supporting CUDA 12.4 (`nvidia-smi` shows it). Otherwise use `TORCH=cpu`.
- Only clone voices you have permission to use.

## Layout

```
voice_core.py      synthesis (device detection, chunking, emotion per segment, wav/mp3 export)
voice_mcp.py       MCP server (FastMCP, stdio)
speak.py           command-line generator
requirements.txt   Python deps (torch is installed separately per platform)
scripts/manage.py  setup/install/models/test/register/doctor (stdlib only)
scripts/bootstrap.sh|ps1  install uv, then run manage.py with Python 3.11
Makefile           thin wrapper around the bootstrap scripts
voices/            your samples (git-ignored)
VoiceOvers/        generated audio (git-ignored)
```
