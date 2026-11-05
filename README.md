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

## Web UI

```bash
make ui
```

Opens an ElevenLabs-style page at <http://127.0.0.1:7860> (Ctrl+C in the terminal stops it; `make ui UI_PORT=7861` for another port).

- **Voice**: every sample in `voices/` is listed, with a ▶ preview. Drop a new file in and press the reload icon.
- **Model**: Standard (Emotion + Pace sliders) or Turbo (faster, sound/style tags). Format MP3/WAV, optional seed.
- **Tags**: click a chip to insert it at the cursor. Tags that work with the selected model are highlighted purple; ones it can't use are red and get removed when generating.

| Model | Tags | What they do |
|---|---|---|
| Standard | `[neutral]` `[calm]` `[serious]` `[warm]` `[confident]` `[happy]` `[excited]` `[dramatic]` | Change emotion/pace **from that point on**. `[neutral]` goes back to the slider values |
| Turbo | `[narration]` `[advertisement]` `[happy]` `[surprised]` `[sarcastic]` `[angry]` `[fear]` `[crying]` `[dramatic]` `[whispering]` | Style tokens Turbo was trained with, passed through as written (results vary by voice) |
| Turbo | `[laugh]` `[chuckle]` `[sigh]` `[gasp]` `[cough]` `[clear throat]` `[sniff]` `[groan]` `[shush]` | Non-speech sounds at that spot |
| Both | `[pause]` `[long pause]` | 0.6 s / 1.2 s of silence |

Each generation shows a progress bar (per sentence chunk), then plays in the bottom player. Files land in `VoiceOvers/` as `<voice>_<first words>.mp3` and show up under **History**.

**Cancel** (or Esc) stops a generation immediately. The model runs in its own process, which Cancel kills, so all its memory is returned right away. The next generation reloads it (~30 s). The model is also unloaded after 10 minutes without work (`VOICE_TOOL_UI_IDLE_MIN`), and when you stop `make ui`. If you reload the page mid-generation, it picks the job back up so you can still cancel it.
The UI loads its own copy of the model, separate from the Claude MCP server.

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
| `make ui` | Web UI at http://127.0.0.1:7860 (`UI_PORT=7861` to change) |
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
| `VOICE_TOOL_UI_IDLE_MIN` | `10` | Web UI unloads the model after this many idle minutes |
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
voice_ui.py        web UI server (Starlette) + tag parsing
ui/index.html      the web UI page (no build step, no CDN)
requirements.txt   Python deps (torch is installed separately per platform)
scripts/manage.py  setup/install/models/test/register/doctor (stdlib only)
scripts/bootstrap.sh|ps1  install uv, then run manage.py with Python 3.11
Makefile           thin wrapper around the bootstrap scripts
voices/            your samples (git-ignored)
VoiceOvers/        generated audio (git-ignored)
```
