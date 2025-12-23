import { PostHog } from 'posthog-node'

import type { AnalyticsEvent } from '@/lib/analytics'
import type { SessionManager } from '@/lib/utils/SessionManager'

let _client: PostHog | undefined

function getPostHogClient(): PostHog {
    if (!_client) {
        _client = new PostHog('sTMFPsFhdP1Ssg', {
            host: 'https://us.i.posthog.com',
            flushAt: 1,
            flushInterval: 0,
        })
    }
    return _client
}

export class AnalyticsService {
    constructor(private sessionManager: SessionManager) {}

    async track(
        event: AnalyticsEvent,
        distinctId: string,
        sessionId?: string,
        properties: Record<string, unknown> = {}
    ): Promise<void> {
        try {
            const client = getPostHogClient()
            const sessionUuid = sessionId ? await this.sessionManager.getSessionUuid(sessionId) : undefined

            client.capture({
                distinctId,
                event,
                properties: {
                    ...(sessionUuid ? { $session_id: sessionUuid } : {}),
                    ...properties,
                },
            })
        } catch {
            // Silent fail - analytics should never break the main flow
        }
    }
}
