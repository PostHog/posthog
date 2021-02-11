import { PluginEvent } from '@posthog/plugin-scaffold'
import * as Sentry from '@sentry/node'
import { DateTime } from 'luxon'

import { PluginsServer } from '../types'

export type IngestEventResponse = { success?: boolean; error?: string }

export async function ingestEvent(server: PluginsServer, event: PluginEvent): Promise<IngestEventResponse> {
    try {
        const { distinct_id, ip, site_url, team_id, now, sent_at, uuid } = event
        await server.eventsProcessor.processEvent(
            distinct_id,
            ip,
            site_url,
            event,
            team_id,
            DateTime.fromISO(now),
            sent_at ? DateTime.fromISO(sent_at) : null,
            uuid! // it will throw if it's undefined
        )
        // We don't want to return the inserted DB entry that `processEvent` returns.
        // This response is passed to piscina and would be discarded anyway.
        return { success: true }
    } catch (e) {
        Sentry.captureException(e)
        return { error: e.message }
    }
}
