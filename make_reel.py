#!/usr/bin/env python3
"""
Assembles the vertical video Reel: a still verse-card image with a slow
Ken Burns zoom, spoken narration, and soft background music underneath —
muxed with ffmpeg into a 1080x1920 MP4 ready for Instagram Reels.

Requires ffmpeg/ffprobe on PATH (pre-installed on GitHub Actions ubuntu
runners via apt, or `sudo apt-get install -y ffmpeg` as a setup step).
"""
import argparse
import json
import subprocess

WIDTH, HEIGHT = 1080, 1920
FPS = 30


def probe_duration(path):
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "json", path],
        capture_output=True, text=True, check=True,
    )
    return float(json.loads(out.stdout)["format"]["duration"])


def make_reel(image_path, narration_path, music_path, output_path,
              music_volume=0.16, tail_seconds=2.5, zoom_amount=0.08):
    """
    image_path:     verse card PNG (any aspect ratio; will be cropped/scaled to 1080x1920)
    narration_path: spoken-verse audio (mp3/wav) from narrate.py
    music_path:     background music bed (mp3); looped/trimmed to fit
    output_path:    destination .mp4
    music_volume:   0-1 relative loudness of the music bed under the narration
    tail_seconds:   extra seconds of video/music after narration ends, so the
                    clip doesn't cut off the instant speech stops
    zoom_amount:    total slow Ken-Burns zoom-in over the clip (0.08 = 8%)
    """
    narration_dur = probe_duration(narration_path)
    total_dur = narration_dur + tail_seconds
    frames = max(1, int(total_dur * FPS))

    # zoompan needs the source pre-scaled well above target res or the zoom
    # steps look blocky; 2x target is plenty of headroom for an 8% zoom.
    zoompan = (
        f"zoompan=z='min(zoom+{zoom_amount / frames:.8f},1+{zoom_amount})'"
        f":d={frames}:s={WIDTH}x{HEIGHT}:fps={FPS}"
    )

    filter_complex = (
        f"[0:v]scale={WIDTH * 2}:{HEIGHT * 2}:force_original_aspect_ratio=increase,"
        f"crop={WIDTH * 2}:{HEIGHT * 2},{zoompan},format=yuv420p[v];"
        f"[2:a]volume={music_volume}[music];"
        f"[1:a][music]amix=inputs=2:duration=longest:dropout_transition=3,"
        f"afade=t=out:st={max(0, total_dur - 1.2):.2f}:d=1.2[aout]"
    )

    cmd = [
        "ffmpeg", "-y",
        "-loop", "1", "-i", image_path,
        "-i", narration_path,
        "-stream_loop", "-1", "-i", music_path,
        "-filter_complex", filter_complex,
        "-map", "[v]", "-map", "[aout]",
        "-t", f"{total_dur:.2f}",
        "-c:v", "libx264", "-preset", "medium", "-crf", "20",
        "-r", str(FPS), "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "192k",
        "-movflags", "+faststart",
        output_path,
    ]
    subprocess.run(cmd, check=True, capture_output=True, text=True)
    return output_path, total_dur


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--image", required=True)
    p.add_argument("--narration", required=True)
    p.add_argument("--music", required=True)
    p.add_argument("--output", required=True)
    p.add_argument("--music-volume", type=float, default=0.16)
    args = p.parse_args()
    try:
        out, dur = make_reel(args.image, args.narration, args.music, args.output,
                              music_volume=args.music_volume)
        print(f"REEL_SAVED={out}")
        print(f"REEL_DURATION={dur:.2f}")
    except subprocess.CalledProcessError as e:
        print("FFMPEG_STDERR:")
        print(e.stderr)
        raise
