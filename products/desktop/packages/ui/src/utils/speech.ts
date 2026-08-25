// Renderer-side speech playback. Two paths, both resolve when playback ends so
// the core queue can serialize utterances one at a time:
//   - ElevenLabs MP3 bytes (synthesized in the host, key stays there) played via
//     a blob object URL — NOT a data: URL, which Chromium won't fully load for a
//     multi-second clip.
//   - the system voice via the Web Speech API (fallback when no key is set).
// Best-effort: every path resolves rather than rejecting, and a single current
// utterance is tracked so stop() and the next line interrupt cleanly.

let currentAudio: HTMLAudioElement | null = null;

/** Remove [audio tags] the system voice would otherwise read aloud. */
export function stripAudioTags(text: string): string {
  return text
    .replace(/\[[^\]]*\]/g, " ")
    .replace(/\s+/g, " ")
    .trim();
}

function base64ToBlob(base64: string, mimeType: string): Blob {
  const bytes = Uint8Array.from(atob(base64), (c) => c.charCodeAt(0));
  return new Blob([bytes], { type: mimeType });
}

export function playAudioBase64(
  base64: string,
  mimeType: string,
): Promise<void> {
  return new Promise((resolve) => {
    stopSpeech();
    let objectUrl: string;
    try {
      objectUrl = URL.createObjectURL(base64ToBlob(base64, mimeType));
    } catch {
      resolve();
      return;
    }
    const audio = new Audio(objectUrl);
    currentAudio = audio;
    const done = () => {
      if (currentAudio === audio) currentAudio = null;
      URL.revokeObjectURL(objectUrl);
      resolve();
    };
    audio.addEventListener("ended", done);
    audio.addEventListener("error", done);
    audio.play().catch(done);
  });
}

export function speakSystemVoice(text: string): Promise<void> {
  return new Promise((resolve) => {
    if (typeof window === "undefined" || !window.speechSynthesis) {
      resolve();
      return;
    }
    const clean = stripAudioTags(text);
    if (!clean) {
      resolve();
      return;
    }
    const utterance = new SpeechSynthesisUtterance(clean);
    utterance.onend = () => resolve();
    utterance.onerror = () => resolve();
    window.speechSynthesis.speak(utterance);
  });
}

export function stopSpeech(): void {
  if (currentAudio) {
    currentAudio.pause();
    currentAudio = null;
  }
  if (window?.speechSynthesis) {
    window.speechSynthesis.cancel();
  }
}

export function isSpeechSupported(): boolean {
  return (
    typeof window !== "undefined" &&
    (typeof window.speechSynthesis !== "undefined" ||
      typeof Audio !== "undefined")
  );
}
