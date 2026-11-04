"""voice-tool MCP server: generate voiceovers in a cloned voice, locally and free.

Engine: Chatterbox (Resemble AI, MIT licence) on CUDA, Apple Silicon (MPS) or CPU.
"""
import os, threading
import voice_core as vc
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("voice-tool")


def _fmt(r):
    msg = f"Saved {r['path']} ({r['duration_s']}s audio, generated in {r['took_s']}s, engine={r['engine']}, voice={r['voice']})"
    return msg + (f"\nNote: {r['note']}" if r["note"] else "")


@mcp.tool()
def generate_voiceover(text: str, emotion: float = 0.5, pace: float = 0.5, engine: str = "standard",
                       voice: str = "", output_dir: str = "", filename: str = "", format: str = "wav",
                       seed: int = 0) -> str:
    """Generate a voiceover in a cloned voice and save it to disk.

    text: the script to speak. Long scripts are split into sentences automatically.
    emotion: (standard engine) expressiveness. 0.3 calm, 0.5 natural, 0.7-0.9 excited/dramatic, avoid >1.2.
             Values below ~0.45 tend to sound flat; 0.55-0.65 sounds most natural for narration.
    pace: (standard engine) cfg weight. 0.3 = slower and more expressive, 0.5 = normal. Use ~0.3 with high emotion.
    engine: "standard" (emotion control, best quality) or "turbo" (faster, supports tags in the text
            like [laugh] [chuckle] [sigh] [cough] [gasp]; ignores emotion/pace; needs a >5 s voice sample).
    voice: voice sample file in voice-tool/voices (default my_voice.*) or an absolute path. See list_voices.
    output_dir: folder to save into (absolute path, ~ allowed). Default: voice-tool/VoiceOvers.
    filename: name without extension (default vo_<timestamp>). Never overwrites; adds _2, _3...
    format: "wav" or "mp3".
    seed: set a number to make a take repeatable; 0 = random (re-run for a different take).
    Tip: natural phrasing comes from punctuation: commas and "..." create pauses.
    For one file with changing emotion, use generate_voiceover_segments instead.
    """
    r = vc.synthesize([{"text": text, "emotion": emotion}], engine=engine, voice=voice,
                      output_dir=output_dir, filename=filename, fmt=format, pace=pace, seed=seed)
    return _fmt(r)


@mcp.tool()
def generate_voiceover_segments(segments: list[dict], pace: float = 0.5, engine: str = "standard",
                                voice: str = "", output_dir: str = "", filename: str = "",
                                format: str = "wav", seed: int = 0) -> str:
    """Generate ONE voiceover file whose emotion changes section by section (e.g. hook / body / CTA).

    segments: list of {"text": str, "emotion": float (optional, default 0.5), "pause_after": seconds (optional, default 0.35)}
      e.g. [{"text": "Stop scrolling!", "emotion": 0.85}, {"text": "Here's how...", "emotion": 0.5, "pause_after": 0.5}]
    Keep each segment to a sentence or paragraph; map script tags like [excited]/[warmly] to emotion values.
    Other arguments are the same as generate_voiceover.
    """
    r = vc.synthesize(segments, engine=engine, voice=voice, output_dir=output_dir,
                      filename=filename, fmt=format, pace=pace, seed=seed)
    return _fmt(r)


@mcp.tool()
def list_voices() -> str:
    """List the voice samples available in voice-tool/voices."""
    files = vc.list_voice_files()
    if not files:
        return f"No voice samples yet. Add a clean 10-30 s recording to {vc.VOICES_DIR} (e.g. my_voice.wav)."
    return "\n".join(files) + f"\n(default: {vc.DEFAULT_VOICE}.*)"


@mcp.tool()
def list_voiceovers(output_dir: str = "", limit: int = 30) -> str:
    """List the most recent generated voiceovers (default folder voice-tool/VoiceOvers)."""
    d = vc.Path(os.path.expanduser(output_dir)) if output_dir else vc.DEFAULT_OUT
    files = sorted([p for p in d.glob("*") if p.suffix in (".wav", ".mp3")], key=os.path.getmtime, reverse=True)
    return "\n".join(str(f) for f in files[:limit]) or f"No voiceovers in {d} yet."


@mcp.tool()
def voice_tool_status() -> str:
    """Check the tool: device, loaded models, voice samples, output folder."""
    return (f"device={vc.device()}  loaded={list(vc._models) or 'none yet'}\n"
            f"voices={vc.list_voice_files() or 'none'} (default {vc.DEFAULT_VOICE}.*)\n"
            f"output={vc.DEFAULT_OUT}  ffmpeg={'yes' if vc.find_ffmpeg() else 'no'}")


if __name__ == "__main__":
    if os.environ.get("VOICE_TOOL_PRELOAD", "0") == "1":
        threading.Thread(target=lambda: vc.load_model("standard"), daemon=True).start()
    mcp.run()
