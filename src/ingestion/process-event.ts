import { DateTime } from 'luxon'
import { PluginsServer, Properties } from 'types'
import { UUIDT } from '../utils'
import { PluginEvent } from '@posthog/plugin-scaffold'

export class EventsProcessor {
    pluginsServer: PluginsServer

    constructor(pluginsServer: PluginsServer) {
        this.pluginsServer = pluginsServer
    }

    async process_event_ee(
        distinct_id: string,
        ip: string,
        site_url: string,
        data: PluginEvent,
        team_id: number,
        now: DateTime,
        sent_at: DateTime | null
    ): Promise<void> {
        const properties: Properties = data.properties ?? {}
        if (data['$set']) {
            properties['$set'] = data['$set']
        }

        const person_uuid = new UUIDT()
        const event_uuid = new UUIDT()
    }
}
