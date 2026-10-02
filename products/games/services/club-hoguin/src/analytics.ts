// Sends anonymous Club Hoguin events to PostHog. Without a project API key, every call is a no-op.
export class Analytics {
    private readonly apiKey: string | undefined
    private readonly host: string
    private hasWarned = false

    constructor(apiKey: string | undefined, host: string) {
        this.apiKey = apiKey
        this.host = host.replace(/\/+$/, '')
    }

    capture(distinctId: string, event: string, properties: Record<string, string | number | boolean>): void {
        if (!this.apiKey) {
            return
        }
        const body = JSON.stringify({
            api_key: this.apiKey,
            event,
            distinct_id: distinctId,
            timestamp: new Date().toISOString(),
            properties: { ...properties, $lib: 'club-hoguin', $process_person_profile: false },
        })
        fetch(`${this.host}/i/v0/e/`, {
            method: 'POST',
            headers: { 'content-type': 'application/json' },
            body,
            signal: AbortSignal.timeout(5_000),
        })
            .then((response) => {
                if (!response.ok && !this.hasWarned) {
                    this.hasWarned = true
                    console.warn(`club-hoguin: PostHog refused an event with status ${response.status}`)
                }
            })
            .catch(() => {
                // Analytics must never take the game down.
            })
    }
}
