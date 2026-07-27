import type { Config } from './config'

export interface CreatedBot {
    id: string
}

export interface ParsedTranscriptEvent {
    speaker: string
    text: string
    isFinal: boolean
}

/**
 * Dispatches a bot into a meeting.
 *
 * Two pieces of configuration make the loop work:
 *  - `output_media.camera` points the bot's camera at a webpage we serve, which is also how the bot
 *    speaks: Recall streams that page's audio into the call, so an `<audio>` element on it is the
 *    bot's voice and the page itself is its video.
 *  - `recording_config.realtime_endpoints` streams finalized and partial transcripts to a websocket
 *    we host, which is what the trigger phrase is detected in.
 */
export async function createBot(config: Config, meetingUrl: string): Promise<CreatedBot> {
    const stageUrl = `${config.publicBaseUrl}/stage?token=${config.sharedSecret}`
    const transcriptUrl = `${config.publicBaseUrl.replace(/^http/, 'ws')}/recall/transcript?token=${config.sharedSecret}`

    const response = await fetch(`${config.recallApiBase}/api/v1/bot/`, {
        method: 'POST',
        headers: {
            Authorization: `Token ${config.recallApiKey}`,
            'Content-Type': 'application/json',
        },
        body: JSON.stringify({
            meeting_url: meetingUrl,
            bot_name: config.botName,
            output_media: {
                camera: {
                    kind: 'webpage',
                    config: { url: stageUrl },
                },
            },
            variant: {
                google_meet: config.recallBotVariant,
                zoom: config.recallBotVariant,
                microsoft_teams: config.recallBotVariant,
            },
            recording_config: {
                transcript: {
                    provider: { [config.transcriptProvider]: {} },
                },
                realtime_endpoints: [
                    {
                        type: 'websocket',
                        url: transcriptUrl,
                        events: ['transcript.data', 'transcript.partial_data'],
                    },
                ],
            },
        }),
    })

    if (!response.ok) {
        throw new Error(`Recall bot creation failed (${response.status}): ${await response.text()}`)
    }

    return (await response.json()) as CreatedBot
}

export async function leaveCall(config: Config, botId: string): Promise<void> {
    const response = await fetch(`${config.recallApiBase}/api/v1/bot/${botId}/leave_call/`, {
        method: 'POST',
        headers: { Authorization: `Token ${config.recallApiKey}` },
    })
    if (!response.ok) {
        throw new Error(`Recall leave_call failed (${response.status}): ${await response.text()}`)
    }
}

function readWords(payload: Record<string, unknown>): string {
    const words = payload.words
    if (!Array.isArray(words)) {
        return typeof payload.text === 'string' ? payload.text : ''
    }
    return words
        .map((word) => (word && typeof word === 'object' ? String((word as { text?: unknown }).text ?? '') : ''))
        .join(' ')
        .replace(/\s+/g, ' ')
        .trim()
}

/**
 * Normalizes a realtime transcript frame into speaker plus text.
 *
 * Recall nests the utterance one or two levels under `data` depending on the event, and the transcript
 * providers differ in whether they send a `words` array or a flat `text` field, so each shape is probed
 * rather than assumed. An unrecognized frame returns null instead of throwing, because a single
 * malformed frame should not drop the socket mid-meeting.
 */
export function parseTranscriptEvent(raw: string): ParsedTranscriptEvent | null {
    let frame: Record<string, unknown>
    try {
        frame = JSON.parse(raw) as Record<string, unknown>
    } catch {
        return null
    }

    const event = typeof frame.event === 'string' ? frame.event : ''
    if (!event.startsWith('transcript.')) {
        return null
    }

    const outer = (frame.data ?? {}) as Record<string, unknown>
    const payload = (outer.data ?? outer) as Record<string, unknown>
    const participant = (payload.participant ?? {}) as Record<string, unknown>

    const text = readWords(payload)
    if (!text) {
        return null
    }

    return {
        speaker: typeof participant.name === 'string' && participant.name ? participant.name : 'Someone',
        text,
        isFinal: event === 'transcript.data',
    }
}
