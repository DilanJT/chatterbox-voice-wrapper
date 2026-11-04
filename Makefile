# voice-tool: local voice cloning TTS (Chatterbox) + MCP server for Claude.
# Works on macOS, Linux and Windows (GNU make; on Windows: `winget install ezwinports.make`).
# Everything is done by scripts/manage.py through scripts/bootstrap.*, which installs uv if missing.

ifeq ($(OS),Windows_NT)
  BOOT := powershell -NoProfile -ExecutionPolicy Bypass -File scripts/bootstrap.ps1
else
  BOOT := sh scripts/bootstrap.sh
endif

.DEFAULT_GOAL := help
.PHONY: help setup install models test register unregister doctor speak clean clean-all

help:
	@echo voice-tool commands:
	@echo   make setup       first-time setup: install + download models + register with Claude
	@echo   make install     create .venv and install torch + Chatterbox for this machine
	@echo   make models      download model weights and render a test clip
	@echo   make test        render a test clip with your voice sample in voices/
	@echo   make register    add the voice-tool MCP server to Claude Desktop / Claude Code
	@echo   make unregister  remove it from Claude
	@echo   make doctor      show OS, GPU, device, voices, ffmpeg
	@echo   make speak TEXT="Hello" ARGS="--emotion 0.7 --mp3"
	@echo   make clean       delete .venv    /    make clean-all  also delete models
	@echo Options: TORCH=cpu or cu124 to force a PyTorch build, SKIP_MODELS=1 to skip downloads

setup install models test register unregister doctor clean clean-all:
	$(BOOT) $@

speak:
	$(BOOT) speak "$(TEXT)" $(ARGS)
