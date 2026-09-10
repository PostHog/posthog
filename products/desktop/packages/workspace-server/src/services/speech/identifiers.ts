export const SPEECH_SYNTHESIZER_SERVICE = Symbol.for(
  "posthog.workspace.speechSynthesizer",
);

export interface SpeechSynthesisResult {
  /** Base64-encoded MP3 audio bytes. */
  audioBase64: string;
  mimeType: string;
}

/**
 * Synthesizes speech audio from text (the API key stays in the host). Returns
 * null when no key is configured or synthesis fails, so the renderer falls back
 * to the system voice. Playback itself happens in the renderer (host-neutral).
 * Best-effort — never throws.
 */
export interface ISpeechSynthesizer {
  synthesize(
    text: string,
    voiceId?: string,
  ): Promise<SpeechSynthesisResult | null>;
}

/** Secure-store key the ElevenLabs API key is saved under. */
export const ELEVENLABS_API_KEY_STORE_KEY = "elevenlabs.apiKey";
