/**
 * Writes the ElevenLabs API key to encrypted host storage. The key never lives
 * in the persisted settings blob or in packages/ui — the host binds this to the
 * secure store (see apps/code desktop-services). The settings UI injects it to
 * save/clear the key; a boolean "configured" flag in the settings store mirrors
 * whether one is set, so the UI never reads the secret back.
 */
export interface ISpeechKeyStore {
  save(apiKey: string): Promise<void>;
  clear(): Promise<void>;
}

export const SPEECH_KEY_STORE = Symbol.for("posthog.ui.speech.keyStore");
