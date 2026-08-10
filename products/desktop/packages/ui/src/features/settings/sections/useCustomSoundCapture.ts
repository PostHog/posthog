import { ANALYTICS_EVENTS } from "@posthog/shared";
import { useSettingsStore } from "@posthog/ui/features/settings/settingsStore";
import { toast } from "@posthog/ui/primitives/toast";
import { track } from "@posthog/ui/shell/analytics";
import {
  blobToDataUrl,
  DURATION_TOLERANCE_MS,
  dataUrlByteLength,
  decodeAudioClip,
  detectSilenceBounds,
  formatDurationSeconds,
  getAudioDurationMs,
  isClipSilent,
  isRecordingSupported,
  MAX_CUSTOM_SOUND_BYTES,
  MAX_CUSTOM_SOUND_DURATION_MS,
  MAX_CUSTOM_SOUND_SECONDS,
  pickRecordingMimeType,
  resolveSaveClip,
  shouldOfferTrim,
  type TrimBounds,
  trimmedDurationMs,
} from "@posthog/ui/utils/customSound";
import { useCallback, useEffect, useMemo, useReducer, useRef } from "react";

interface CapturedClip {
  dataUrl: string;
  durationMs: number;
  // How the clip was captured — reported in the "Custom sound added" event.
  source: "recording" | "import";
  // Decoded samples, present whenever the clip could be decoded. Absent for
  // exotic containers, where we store the clip untrimmed.
  buffer: AudioBuffer | null;
  // The span left after stripping leading/trailing silence, when there's enough
  // silence to bother offering. Null means nothing worth trimming.
  silenceBounds: TrimBounds | null;
}

// All the dialog's transient state lives in one reducer so a single logical
// step (e.g. "recording started") is one update rather than a fan-out of
// separate setters.
interface DialogState {
  name: string;
  clip: CapturedClip | null;
  error: string | null;
  isRecording: boolean;
  elapsedMs: number;
  // Whether the offered silence trim is applied. The trim region is always the
  // clip's detected silence bounds, so this is just a toggle.
  isTrimmed: boolean;
}

type DialogAction =
  | { type: "setName"; name: string }
  | { type: "error"; message: string }
  | { type: "recordingStarted" }
  | { type: "recordingStopped" }
  | { type: "tick"; elapsedMs: number }
  | { type: "clipReady"; clip: CapturedClip }
  | { type: "setTrimmed"; isTrimmed: boolean }
  | { type: "clearClip" }
  | { type: "reset" };

const INITIAL_STATE: DialogState = {
  name: "",
  clip: null,
  error: null,
  isRecording: false,
  elapsedMs: 0,
  isTrimmed: false,
};

function reducer(state: DialogState, action: DialogAction): DialogState {
  switch (action.type) {
    case "setName":
      return { ...state, name: action.name };
    case "error":
      return { ...state, error: action.message, isRecording: false };
    case "recordingStarted":
      return {
        ...state,
        error: null,
        clip: null,
        isRecording: true,
        elapsedMs: 0,
        isTrimmed: false,
      };
    case "recordingStopped":
      return { ...state, isRecording: false };
    case "tick":
      return { ...state, elapsedMs: action.elapsedMs };
    case "clipReady":
      // A fresh clip is never pre-trimmed.
      return { ...state, clip: action.clip, error: null, isTrimmed: false };
    case "setTrimmed":
      return { ...state, isTrimmed: action.isTrimmed };
    case "clearClip":
      return { ...state, clip: null, isTrimmed: false };
    case "reset":
      return INITIAL_STATE;
    default:
      return state;
  }
}

// Everything the Add-custom-sound dialog does except render: recorder/stream
// lifecycle, file import, decode + silence detection, trimmed preview, and
// save. The component consumes the returned view-model and handlers.
export function useCustomSoundCapture(onOpenChange: (open: boolean) => void) {
  const addCustomSound = useSettingsStore((s) => s.addCustomSound);
  const setCompletionSound = useSettingsStore((s) => s.setCompletionSound);

  const [state, dispatch] = useReducer(reducer, INITIAL_STATE);
  const { name, clip, error, isRecording, elapsedMs, isTrimmed } = state;
  // The trim region is always the detected silence bounds; isTrimmed just
  // toggles whether it's applied.
  const trim: TrimBounds | null = isTrimmed
    ? (clip?.silenceBounds ?? null)
    : null;

  const recorderRef = useRef<MediaRecorder | null>(null);
  const chunksRef = useRef<Blob[]>([]);
  const streamRef = useRef<MediaStream | null>(null);
  const timerRef = useRef<number | null>(null);
  const previewRef = useRef<HTMLAudioElement | null>(null);
  const audioCtxRef = useRef<AudioContext | null>(null);
  const sourceRef = useRef<AudioBufferSourceNode | null>(null);
  // Monotonic capture id. An in-flight acceptBlob (awaiting decode/duration
  // read) checks this before dispatching and bails if a newer capture started
  // or the dialog reset/closed — so a stale result can't repopulate a reopened
  // dialog or let an older import overwrite a newer selection.
  const captureSeqRef = useRef(0);

  const stopStream = useCallback(() => {
    for (const track of streamRef.current?.getTracks() ?? []) {
      track.stop();
    }
    streamRef.current = null;
  }, []);

  const stopTimer = useCallback(() => {
    if (timerRef.current !== null) {
      window.clearInterval(timerRef.current);
      timerRef.current = null;
    }
  }, []);

  const stopPreview = useCallback(() => {
    if (sourceRef.current) {
      try {
        sourceRef.current.stop();
      } catch {
        // Already stopped — fine.
      }
      sourceRef.current = null;
    }
    previewRef.current?.pause();
  }, []);

  // Tear down any in-flight recorder/stream/timer/preview. Detaches the
  // recorder's handlers first so a late onstop can't dispatch into a dialog
  // that's already closing.
  const releaseResources = useCallback(() => {
    // Supersede any in-flight capture so its decode can't dispatch post-close.
    captureSeqRef.current++;
    stopTimer();
    const recorder = recorderRef.current;
    if (recorder) {
      recorder.onstop = null;
      recorder.ondataavailable = null;
      if (recorder.state !== "inactive") recorder.stop();
      recorderRef.current = null;
    }
    stopStream();
    stopPreview();
    previewRef.current = null;
    audioCtxRef.current?.close().catch(() => {});
    audioCtxRef.current = null;
  }, [stopStream, stopTimer, stopPreview]);

  const stopRecording = useCallback(() => {
    stopTimer();
    const recorder = recorderRef.current;
    if (recorder && recorder.state !== "inactive") recorder.stop();
    dispatch({ type: "recordingStopped" });
  }, [stopTimer]);

  // Validate a captured/imported blob, decode it (so we can detect silence and
  // re-encode a trimmed copy), then stash it as the pending clip.
  // `fallbackDurationMs` is used when the container doesn't expose a duration
  // (common for freshly-recorded WebM), where the recorder's elapsed time wins.
  const acceptBlob = useCallback(
    async (
      blob: Blob,
      fallbackDurationMs: number | null,
      source: "recording" | "import",
    ) => {
      // Tag this capture. If a newer capture starts, or the dialog resets /
      // closes, while we're awaiting decode/duration-read, the commits below
      // no-op — so a stale result can't repopulate a reopened dialog or
      // overwrite a newer clip.
      const myCapture = ++captureSeqRef.current;
      const commit = (action: DialogAction) => {
        if (captureSeqRef.current === myCapture) dispatch(action);
      };

      let dataUrl: string;
      try {
        dataUrl = await blobToDataUrl(blob);
      } catch {
        commit({
          type: "error",
          message: "Could not read the audio data. Try a different file.",
        });
        return;
      }
      if (dataUrlByteLength(dataUrl) > MAX_CUSTOM_SOUND_BYTES) {
        commit({
          type: "error",
          message: "That clip is too large. Keep it short (max ~1 MB).",
        });
        return;
      }
      const buffer = await decodeAudioClip(blob);
      const decoded = buffer
        ? buffer.duration * 1000
        : await getAudioDurationMs(dataUrl);
      // Live recordings pass the recorder's elapsed time (always ≤ MAX); file
      // imports pass null, so if we also can't decode/read the duration we
      // reject rather than defaulting to 0 and silently bypassing the cap.
      const durationMs = decoded ?? fallbackDurationMs;
      if (
        durationMs === null ||
        durationMs > MAX_CUSTOM_SOUND_DURATION_MS + DURATION_TOLERANCE_MS
      ) {
        commit({
          type: "error",
          message:
            durationMs === null
              ? "Couldn't read the clip's duration. Try a different format (MP3 or WAV work reliably)."
              : `Clips must be ${MAX_CUSTOM_SOUND_SECONDS}s or shorter.`,
        });
        return;
      }
      // A recording that comes back silent means the mic delivered no audio
      // (often the OS still blocks microphone access even though the browser
      // reports it granted). Saving it would produce a sound that plays
      // nothing, so reject it with a pointer at the likely cause.
      if (source === "recording" && buffer && isClipSilent(buffer)) {
        // Quantifies the macOS "browser says mic granted but the OS delivers
        // silence" case (e.g. unsigned dev builds).
        track(ANALYTICS_EVENTS.CUSTOM_SOUND_RECORDING_SILENT);
        commit({
          type: "error",
          message:
            "We didn't pick up any audio. Check that PostHog has microphone access, then try again.",
        });
        return;
      }
      // Only surface the trim offer when there's a meaningful amount of silence
      // to strip from either end.
      const bounds = buffer ? detectSilenceBounds(buffer) : null;
      commit({
        type: "clipReady",
        clip: {
          dataUrl,
          durationMs,
          source,
          buffer,
          silenceBounds: shouldOfferTrim(bounds, durationMs / 1000)
            ? bounds
            : null,
        },
      });
    },
    [],
  );

  const startRecording = useCallback(async () => {
    // A new recording supersedes any in-flight import decode.
    captureSeqRef.current++;
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      streamRef.current = stream;
      const mimeType = pickRecordingMimeType();
      const recorder = new MediaRecorder(
        stream,
        mimeType ? { mimeType } : undefined,
      );
      chunksRef.current = [];
      const startedAt = Date.now();
      recorder.ondataavailable = (event) => {
        if (event.data.size > 0) chunksRef.current.push(event.data);
      };
      recorder.onstop = () => {
        const elapsed = Math.min(
          Date.now() - startedAt,
          MAX_CUSTOM_SOUND_DURATION_MS,
        );
        stopStream();
        const blob = new Blob(chunksRef.current, {
          type: recorder.mimeType || "audio/webm",
        });
        void acceptBlob(blob, elapsed, "recording");
      };
      recorder.start();
      recorderRef.current = recorder;
      dispatch({ type: "recordingStarted" });
      timerRef.current = window.setInterval(() => {
        const elapsed = Date.now() - startedAt;
        dispatch({ type: "tick", elapsedMs: elapsed });
        if (elapsed >= MAX_CUSTOM_SOUND_DURATION_MS) stopRecording();
      }, 100);
    } catch {
      stopStream();
      dispatch({
        type: "error",
        message:
          "Microphone access was blocked. Allow it in your system settings.",
      });
    }
  }, [acceptBlob, stopRecording, stopStream]);

  const importFile = useCallback(
    async (file: File | undefined) => {
      if (!file) return;
      if (!file.type.startsWith("audio/")) {
        dispatch({ type: "error", message: "Choose an audio file." });
        return;
      }
      if (file.size > MAX_CUSTOM_SOUND_BYTES) {
        dispatch({
          type: "error",
          message: "That file is too large. Keep it short (max ~1 MB).",
        });
        return;
      }
      if (!name.trim()) {
        // Seed the name from the filename so the user has a sensible default.
        dispatch({ type: "setName", name: file.name.replace(/\.[^.]+$/, "") });
      }
      await acceptBlob(file, null, "import");
    },
    [acceptBlob, name],
  );

  // Preview the current selection. Web Audio plays the exact [start, end] slice
  // of the decoded buffer, which sidesteps the unreliable seeking of
  // freshly-recorded WebM; the <audio> path is a fallback for undecodable clips.
  const playPreview = useCallback(() => {
    if (!clip) return;
    stopPreview();
    if (clip.buffer) {
      try {
        if (!audioCtxRef.current) audioCtxRef.current = new AudioContext();
        const ctx = audioCtxRef.current;
        const startSec = trim?.startSec ?? 0;
        const endSec = trim?.endSec ?? clip.buffer.duration;
        const src = ctx.createBufferSource();
        src.buffer = clip.buffer;
        src.connect(ctx.destination);
        src.start(0, startSec, Math.max(0, endSec - startSec));
        sourceRef.current = src;
        void ctx.resume();
        return;
      } catch {
        // Fall through to the element-based preview.
      }
    }
    const audio = new Audio(clip.dataUrl);
    previewRef.current = audio;
    audio.play().catch(() => {
      // Ignore — preview is best-effort.
    });
  }, [clip, trim, stopPreview]);

  const toggleTrim = useCallback(() => {
    stopPreview();
    dispatch({ type: "setTrimmed", isTrimmed: !isTrimmed });
  }, [isTrimmed, stopPreview]);

  const discardClip = useCallback(() => {
    // Supersede any in-flight capture so it can't repopulate after discard.
    captureSeqRef.current++;
    stopPreview();
    dispatch({ type: "clearClip" });
  }, [stopPreview]);

  // Reset on close in the close handler itself (not a useEffect watching
  // `open`) so there's no extra render showing stale state between commits.
  const handleOpenChange = useCallback(
    (next: boolean) => {
      if (!next) {
        releaseResources();
        dispatch({ type: "reset" });
      }
      onOpenChange(next);
    },
    [onOpenChange, releaseResources],
  );

  // Release media resources if the dialog unmounts mid-recording.
  useEffect(() => releaseResources, [releaseResources]);

  const save = useCallback(() => {
    const trimmed = name.trim();
    if (!trimmed || !clip) return;
    const resolved = resolveSaveClip(clip, trim);
    if ("error" in resolved) {
      dispatch({ type: "error", message: resolved.error });
      return;
    }
    const id = crypto.randomUUID();
    addCustomSound({
      id,
      name: trimmed,
      dataUrl: resolved.dataUrl,
      durationMs: resolved.durationMs,
    });
    setCompletionSound(`custom:${id}`);
    track(ANALYTICS_EVENTS.CUSTOM_SOUND_ADDED, {
      source: clip.source,
      trimmed: trim !== null,
      duration_ms: resolved.durationMs,
    });
    toast.success(`Added "${trimmed}"`);
    handleOpenChange(false);
  }, [addCustomSound, clip, handleOpenChange, name, setCompletionSound, trim]);

  const setName = useCallback(
    (value: string) => dispatch({ type: "setName", name: value }),
    [],
  );
  // Capability is fixed for the session; don't recompute it every render/tick.
  const recordingSupported = useMemo(() => isRecordingSupported(), []);

  const shownDurationMs = trim
    ? trimmedDurationMs(trim)
    : (clip?.durationMs ?? 0);

  return {
    // form / status
    name,
    setName,
    error,
    isRecording,
    recordingSupported,
    elapsedLabel: formatDurationSeconds(elapsedMs),
    // captured clip
    hasClip: clip !== null && !isRecording,
    isTrimmed: trim !== null,
    canOfferTrim: clip?.silenceBounds != null,
    clipDurationLabel: formatDurationSeconds(shownDurationMs),
    canSave: name.trim().length > 0 && clip !== null && !isRecording,
    // actions
    startRecording,
    stopRecording,
    importFile,
    playPreview,
    toggleTrim,
    discardClip,
    save,
    handleOpenChange,
  };
}
