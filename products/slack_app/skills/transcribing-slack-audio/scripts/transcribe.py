#!/usr/bin/env python3
"""Transcribe Slack voice messages and audio attachments on this machine.

The audio never leaves the sandbox: ffprobe measures it, ffmpeg converts it to 16 kHz mono
WAV, and whisper.cpp (`whisper-cli`) transcribes it with a local model. Nothing here opens a
network connection.

    python3 transcribe.py /path/to/audio_message.m4a [more files...]
    python3 transcribe.py --language de memo.ogg

The transcript goes to stdout, one block per file. Status and errors go to stderr, each error
on a line that starts with "error:". Exit codes:

    0  every file was transcribed
    1  at least one file failed (the others are still printed)
    2  bad arguments
    3  ffmpeg, ffprobe, whisper-cli, or the model is missing
"""

from __future__ import annotations

import os
import re
import sys
import json
import time
import shutil
import argparse
import tempfile
import subprocess
from pathlib import Path

# Matches TASK_RUN_ARTIFACT_MAX_SIZE_BYTES, the largest attachment that reaches the sandbox.
# The duration and processing limits below are the real bounds. This cap only stops a file
# that could not have come from an attachment.
MAX_FILE_BYTES = 30 * 1024 * 1024
DEFAULT_MAX_DURATION_SECONDS = 5 * 60
DEFAULT_TIMEOUT_SECONDS = 5 * 60
PROBE_TIMEOUT_SECONDS = 30
DEFAULT_MODEL_PATH = "/opt/whisper/models/ggml-small-q5_1.bin"
MODEL_PATH_ENV = "WHISPER_MODEL_PATH"

EXIT_OK = 0
EXIT_FAILED = 1
EXIT_USAGE = 2
EXIT_MISSING_TOOLS = 3

# whisper.cpp writes these markers for silence or noise instead of words.
_NON_SPEECH_MARKER = re.compile(r"\[(?:BLANK_AUDIO|MUSIC|NOISE|SILENCE|INAUDIBLE)\]|\((?:silence|music|noise)\)", re.I)


class TranscriptionError(Exception):
    pass


def _error(message: str) -> None:
    print(f"error: {message}", file=sys.stderr)


def _run(command: list[str], *, timeout: float, limit_seconds: int, step: str) -> subprocess.CompletedProcess[str]:
    """Run one tool. `subprocess.run` kills the child when the timeout expires."""
    stopped = TranscriptionError(f"processing passed the {limit_seconds} second limit during {step} and was stopped")
    if timeout <= 0:
        raise stopped
    try:
        return subprocess.run(command, capture_output=True, text=True, timeout=timeout, check=False, stdin=subprocess.DEVNULL)
    except subprocess.TimeoutExpired:
        raise stopped


def available_cpus() -> int:
    """CPUs this process may use, capped at 8 because whisper.cpp gains little past that.

    `os.cpu_count()` reports the host. A container usually gets fewer CPUs through its
    affinity mask or a cgroup quota, and more threads than CPUs makes whisper.cpp slower.
    """
    count = len(os.sched_getaffinity(0)) if hasattr(os, "sched_getaffinity") else os.cpu_count() or 1
    try:
        quota, period = Path("/sys/fs/cgroup/cpu.max").read_text().split()[:2]
        if quota != "max":
            count = min(count, max(1, -(-int(quota) // int(period))))
    except (OSError, ValueError):
        pass
    return max(1, min(count, 8))


def _tail(text: str, lines: int = 5) -> str:
    return " | ".join(line.strip() for line in text.strip().splitlines()[-lines:] if line.strip())


def missing_tools(model_path: Path) -> list[str]:
    missing = [tool for tool in ("ffprobe", "ffmpeg", "whisper-cli") if shutil.which(tool) is None]
    if not model_path.is_file():
        missing.append(f"whisper model at {model_path} (set {MODEL_PATH_ENV} to another ggml model)")
    return missing


def probe_duration_seconds(audio: Path) -> float:
    result = _run(
        [
            "ffprobe",
            "-v",
            "error",
            "-select_streams",
            "a",
            "-show_entries",
            "stream=index:format=duration",
            "-of",
            "json",
            str(audio),
        ],
        timeout=PROBE_TIMEOUT_SECONDS,
        limit_seconds=PROBE_TIMEOUT_SECONDS,
        step="reading the audio metadata",
    )
    if result.returncode != 0:
        raise TranscriptionError(f"ffprobe could not read the file as audio ({_tail(result.stderr) or 'no details'})")
    try:
        info = json.loads(result.stdout or "{}")
    except json.JSONDecodeError:
        raise TranscriptionError("ffprobe returned unreadable metadata")
    if not info.get("streams"):
        raise TranscriptionError("the file has no audio stream")
    try:
        return float(info["format"]["duration"])
    except (KeyError, TypeError, ValueError):
        raise TranscriptionError("the recording length is unknown, so the duration limit cannot be checked")


def transcribe_file(
    audio: Path,
    *,
    model_path: Path,
    language: str,
    max_duration_seconds: int,
    timeout_seconds: int,
    threads: int,
) -> tuple[str, str | None, float]:
    """Return the transcript, the detected language, and the duration in seconds."""
    if not audio.is_file():
        raise TranscriptionError("file not found")
    size = audio.stat().st_size
    if size == 0:
        raise TranscriptionError("the file is empty")
    if size > MAX_FILE_BYTES:
        raise TranscriptionError(f"the file is {size / 1024 / 1024:.1f} MB, over the {MAX_FILE_BYTES // 1024 // 1024} MB limit")

    deadline = time.monotonic() + timeout_seconds
    duration = probe_duration_seconds(audio)
    if duration > max_duration_seconds:
        raise TranscriptionError(
            f"the recording is {duration / 60:.1f} minutes long, over the {max_duration_seconds / 60:g} minute limit"
        )

    with tempfile.TemporaryDirectory(prefix="slack-audio-") as workdir:
        wav = Path(workdir) / "audio.wav"
        result = _run(
            [
                "ffmpeg",
                "-nostdin",
                "-hide_banner",
                "-loglevel",
                "error",
                "-y",
                "-i",
                str(audio),
                # The probe can underreport a damaged file, so the conversion cuts at the limit too.
                "-t",
                str(max_duration_seconds),
                "-vn",
                "-ac",
                "1",
                "-ar",
                "16000",
                "-c:a",
                "pcm_s16le",
                str(wav),
            ],
            timeout=deadline - time.monotonic(),
            limit_seconds=timeout_seconds,
            step="converting the audio",
        )
        if result.returncode != 0 or not wav.is_file():
            raise TranscriptionError(f"ffmpeg could not decode the audio ({_tail(result.stderr) or 'no details'})")

        output_base = Path(workdir) / "transcript"
        result = _run(
            [
                "whisper-cli",
                "--model",
                str(model_path),
                "--file",
                str(wav),
                "--language",
                language,
                "--threads",
                str(threads),
                # Greedy decoding. Beam search is several times slower on CPU for a small gain.
                "--beam-size",
                "1",
                "--best-of",
                "1",
                "--no-prints",
                "--output-json",
                "--output-file",
                str(output_base),
            ],
            timeout=deadline - time.monotonic(),
            limit_seconds=timeout_seconds,
            step="transcription",
        )
        json_path = output_base.with_suffix(".json")
        if result.returncode != 0 or not json_path.is_file():
            raise TranscriptionError(f"whisper-cli failed ({_tail(result.stderr) or 'no details'})")
        try:
            data = json.loads(json_path.read_text(encoding="utf-8", errors="replace"))
        except json.JSONDecodeError:
            raise TranscriptionError("whisper-cli wrote an unreadable transcript")

    segments = [str(segment.get("text") or "") for segment in data.get("transcription") or []]
    text = " ".join(" ".join(_NON_SPEECH_MARKER.sub(" ", segment).split()) for segment in segments).strip()
    text = " ".join(text.split())
    if not text:
        raise TranscriptionError("no speech was detected in the recording")
    detected = (data.get("result") or {}).get("language")
    return text, detected if isinstance(detected, str) and detected else None, duration


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Transcribe audio files locally with whisper.cpp.")
    parser.add_argument("files", nargs="+", type=Path, help="audio files to transcribe")
    parser.add_argument(
        "--language",
        default="auto",
        help="spoken language as an ISO 639-1 code such as en or de, or auto to detect it (default: auto)",
    )
    parser.add_argument(
        "--max-duration-seconds",
        type=int,
        default=DEFAULT_MAX_DURATION_SECONDS,
        help=f"refuse longer recordings (default and maximum: {DEFAULT_MAX_DURATION_SECONDS})",
    )
    parser.add_argument(
        "--timeout-seconds",
        type=int,
        default=DEFAULT_TIMEOUT_SECONDS,
        help=f"processing time allowed per file (default and maximum: {DEFAULT_TIMEOUT_SECONDS})",
    )
    args = parser.parse_args(argv)

    if not re.fullmatch(r"auto|[a-z]{2,3}", args.language):
        _error(f"--language must be auto or a two- or three-letter language code, not {args.language!r}")
        return EXIT_USAGE
    # The limits can be lowered but not raised, so a caller cannot opt out of them.
    if not 0 < args.max_duration_seconds <= DEFAULT_MAX_DURATION_SECONDS:
        _error(f"--max-duration-seconds must be between 1 and {DEFAULT_MAX_DURATION_SECONDS}")
        return EXIT_USAGE
    if not 0 < args.timeout_seconds <= DEFAULT_TIMEOUT_SECONDS:
        _error(f"--timeout-seconds must be between 1 and {DEFAULT_TIMEOUT_SECONDS}")
        return EXIT_USAGE

    model_path = Path(os.environ.get(MODEL_PATH_ENV) or DEFAULT_MODEL_PATH)
    missing = missing_tools(model_path)
    if missing:
        _error(f"local transcription is not available in this environment. Missing: {', '.join(missing)}")
        return EXIT_MISSING_TOOLS

    threads = available_cpus()
    failed = False
    for audio in args.files:
        try:
            text, language, duration = transcribe_file(
                audio,
                model_path=model_path,
                language=args.language,
                max_duration_seconds=args.max_duration_seconds,
                timeout_seconds=args.timeout_seconds,
                threads=threads,
            )
        except TranscriptionError as error:
            failed = True
            _error(f"{audio.name}: {error}")
            continue
        print(f"{audio.name}: transcribed {duration:.0f}s of audio, language {language or args.language}", file=sys.stderr)
        print(f"=== {audio.name} ===\n{text}\n")
    return EXIT_FAILED if failed else EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
