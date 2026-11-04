"""CLI: python speak.py "Text to say" [--emotion 0.7] [--pace 0.4] [--engine turbo] [--voice my_voice.wav]
                                      [--out ~/Desktop] [--name intro] [--mp3] [--seed 42]
Or via make:  make speak TEXT="Text to say" ARGS="--emotion 0.7 --mp3" """
import argparse, voice_core as vc

ap = argparse.ArgumentParser(description="Generate a voiceover in a cloned voice")
ap.add_argument("text")
ap.add_argument("--emotion", type=float, default=0.5)
ap.add_argument("--pace", type=float, default=0.5)
ap.add_argument("--engine", default="standard", choices=["standard", "turbo"])
ap.add_argument("--voice", default="")
ap.add_argument("--out", default="")
ap.add_argument("--name", default="")
ap.add_argument("--mp3", action="store_true")
ap.add_argument("--seed", type=int, default=0)
a = ap.parse_args()
r = vc.synthesize([{"text": a.text, "emotion": a.emotion}], engine=a.engine, voice=a.voice, output_dir=a.out,
                  filename=a.name, fmt="mp3" if a.mp3 else "wav", pace=a.pace, seed=a.seed)
print(f"Saved {r['path']} ({r['duration_s']}s, {r['took_s']}s)" + (f"  {r['note']}" if r['note'] else ""))
