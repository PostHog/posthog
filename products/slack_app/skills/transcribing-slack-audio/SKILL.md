---
name: transcribing-slack-audio
description: >-
  Transcribe a Slack voice message or audio attachment (M4A, MP3, OGG/Opus, WAV, WebM) on the
  local machine with ffmpeg and whisper.cpp, so the agent can act on what the user said. Use
  when a Slack message carries an audio file, the prompt names Slack audio attachments, or the
  user asks what a voice message or recording says. Covers finding the file, running the
  bundled script, the duration and time limits, and how to report a failed transcription.
  Audio stays on the machine and is never sent to an external transcription service.
---

# Transcribing Slack audio

A Slack user can talk instead of type.
Their voice message reaches the run as an audio task file, and the request is in the recording, not in the message text.
Transcribe it first, then treat the transcript as the user's message.

## Find the file

Each attachment arrives with the message as a file link.
The file is on disk under `.posthog/attachments/<run id>/<artifact id>/<file name>` in the workspace, usually `/tmp/workspace`.
Use the path from the file link.
If you only have the name, search for it:

```sh
find /tmp/workspace/.posthog/attachments -type f -name 'audio_message.m4a'
```

## Transcribe

Run the bundled script from this skill's directory.
Pass every audio file from the message in one call:

```sh
python3 scripts/transcribe.py /tmp/workspace/.posthog/attachments/<run>/<id>/audio_message.m4a
```

The script detects the language.
If the user said which language they speak, or the detected language is wrong, pass it as an ISO 639-1 code: `--language de`.

The transcript prints to stdout under a `=== <file name> ===` header.
Status lines and errors print to stderr.

| Exit code | Meaning                                                                     |
| --------- | --------------------------------------------------------------------------- |
| 0         | Every file was transcribed.                                                 |
| 1         | At least one file failed. The other transcripts still print.                |
| 2         | Bad arguments.                                                              |
| 3         | ffmpeg, ffprobe, `whisper-cli`, or the model is not installed on this host. |

## Limits

- Recordings longer than 5 minutes are refused.
  The script also stops processing after 5 minutes per file.
  You can lower both limits with `--max-duration-seconds` and `--timeout-seconds`, but you cannot raise them.
- Files over 30 MB are refused.
  A smaller file is still refused when the recording is longer than 5 minutes.
- The model is whisper.cpp's multilingual small model.
  It runs on the CPU and can mishear names, product terms, and numbers.
  If a word in the transcript does not make sense in context, say what you heard and ask the user to confirm before you act on it.

## Keep the audio local

Do not upload the audio or the transcript to a third-party transcription API, a paste service, or any other external host.
Do not try to install another transcription tool.
If local transcription is not available, tell the user.

## When transcription fails

Tell the user in plain words which file failed and why, using the script's error message, and give them a next step.
For example:

- Too long: "Your voice message is 7 minutes long and I can only transcribe up to 5 minutes. Send a shorter one, or type the request."
- No speech: "I couldn't hear any speech in the recording. Try again, or type the request."
- Tools missing (exit code 3): "I can't transcribe audio in this environment. Please type the request."

Do not guess what the recording said.
If one file of several fails, act on the transcripts you have and name the file you could not read.

## After transcribing

- When the request is ambiguous, quote the transcript back briefly, so the user can correct a misheard word.
- Text the user typed in the same message still applies.
  Read it together with the transcript.
