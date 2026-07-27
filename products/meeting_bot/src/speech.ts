import { randomUUID } from 'node:crypto'

import type { Config } from './config'

interface StoredClip {
    audio: Buffer
    expiresAt: number
}

/**
 * Synthesizes speech and holds the result in memory just long enough for the stage page to fetch it.
 *
 * The clip is served over HTTP rather than pushed down the websocket because the browser inside Recall's
 * output-media instance can start playing a streamed response before the whole file has arrived, which is
 * the difference between the bot answering promptly and pausing for a beat first.
 */
export class SpeechSynthesizer {
    private readonly clips = new Map<string, StoredClip>()

    constructor(private readonly config: Config) {}

    async synthesize(text: string): Promise<{ url: string }> {
        const response = await fetch(
            `https://api.elevenlabs.io/v1/text-to-speech/${this.config.elevenLabsVoiceId}?output_format=mp3_44100_128`,
            {
                method: 'POST',
                headers: {
                    'xi-api-key': this.config.elevenLabsApiKey,
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify({
                    text,
                    model_id: this.config.elevenLabsModelId,
                }),
            }
        )

        if (!response.ok) {
            throw new Error(`Speech synthesis failed (${response.status}): ${await response.text()}`)
        }

        const id = randomUUID()
        this.clips.set(id, {
            audio: Buffer.from(await response.arrayBuffer()),
            expiresAt: Date.now() + 5 * 60 * 1000,
        })
        this.evictExpired()

        return { url: `${this.config.publicBaseUrl}/audio/${id}.mp3` }
    }

    take(id: string): Buffer | null {
        const clip = this.clips.get(id)
        if (!clip || clip.expiresAt < Date.now()) {
            return null
        }
        return clip.audio
    }

    private evictExpired(): void {
        const now = Date.now()
        for (const [id, clip] of this.clips) {
            if (clip.expiresAt < now) {
                this.clips.delete(id)
            }
        }
    }
}
