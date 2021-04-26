import { PluginEvent } from '@posthog/plugin-scaffold'

import { processError } from '../../shared/error'
import { PluginConfig, PluginsServer } from '../../types'

export async function runPlugins(server: PluginsServer, event: PluginEvent): Promise<PluginEvent | null> {
    const pluginsToRun = getPluginsForTeam(server, event.team_id)
    let returnedEvent: PluginEvent | null = event

    const pluginsSucceeded = []
    const pluginsFailed = []
    for (const pluginConfig of pluginsToRun) {
        const processEvent = await pluginConfig.vm?.getProcessEvent()

        if (processEvent) {
            const timer = new Date()

            try {
                returnedEvent = (await processEvent(returnedEvent)) || null
                pluginsSucceeded.push(`${pluginConfig.plugin?.name} (${pluginConfig.id})`)
            } catch (error) {
                await processError(server, pluginConfig, error, returnedEvent)
                server.statsd?.increment(`plugin.${pluginConfig.plugin?.name}.process_event.ERROR`)
                pluginsFailed.push(`${pluginConfig.plugin?.name} (${pluginConfig.id})`)
            }
            server.statsd?.timing(`plugin.${pluginConfig.plugin?.name}.process_event`, timer)

            if (!returnedEvent) {
                return null
            }
        }
    }

    if (pluginsSucceeded.length > 0 || pluginsFailed.length > 0) {
        event.properties = {
            ...event.properties,
            $plugins_succeeded: pluginsSucceeded,
            $plugins_failed: pluginsFailed,
        }
    }

    return returnedEvent
}

export async function runPluginsOnBatch(server: PluginsServer, batch: PluginEvent[]): Promise<PluginEvent[]> {
    const eventsByTeam = new Map<number, PluginEvent[]>()

    for (const event of batch) {
        if (eventsByTeam.has(event.team_id)) {
            eventsByTeam.get(event.team_id)!.push(event)
        } else {
            eventsByTeam.set(event.team_id, [event])
        }
    }

    let allReturnedEvents: PluginEvent[] = []

    for (const [teamId, teamEvents] of eventsByTeam.entries()) {
        const pluginsToRun = getPluginsForTeam(server, teamId)

        let returnedEvents: PluginEvent[] = teamEvents
        const pluginsSucceeded = []
        const pluginsFailed = []
        for (const pluginConfig of pluginsToRun) {
            const timer = new Date()
            const processEventBatch = await pluginConfig.vm?.getProcessEventBatch()
            if (processEventBatch && returnedEvents.length > 0) {
                try {
                    returnedEvents = (await processEventBatch(returnedEvents)) || []
                    pluginsSucceeded.push(`${pluginConfig.plugin?.name} (${pluginConfig.id})`)
                } catch (error) {
                    await processError(server, pluginConfig, error, returnedEvents[0])
                    server.statsd?.increment(`plugin.${pluginConfig.plugin?.name}.process_event_batch.ERROR`)
                    pluginsFailed.push(`${pluginConfig.plugin?.name} (${pluginConfig.id})`)
                }
                server.statsd?.timing(`plugin.${pluginConfig.plugin?.name}.process_event_batch`, timer)
                server.statsd?.timing('plugin.process_event_batch', timer, 0.2, {
                    plugin: pluginConfig.plugin?.name ?? '?',
                    teamId: teamId.toString(),
                })
            }
        }

        for (const event of returnedEvents) {
            if (event && (pluginsSucceeded.length > 0 || pluginsFailed.length > 0)) {
                event.properties = {
                    ...event.properties,
                    $plugins_succeeded: pluginsSucceeded,
                    $plugins_failed: pluginsFailed,
                }
            }
        }

        allReturnedEvents = allReturnedEvents.concat(returnedEvents)
    }

    return allReturnedEvents.filter(Boolean)
}

export async function runPluginTask(server: PluginsServer, taskName: string, pluginConfigId: number): Promise<any> {
    const timer = new Date()
    let response
    try {
        const pluginConfig = server.pluginConfigs.get(pluginConfigId)
        const task = await pluginConfig?.vm?.getTask(taskName)
        response = await task?.exec()
    } catch (error) {
        await processError(server, pluginConfigId, error)
        server.statsd?.increment(`plugin.task.${taskName}.${pluginConfigId}.ERROR`)
    }
    server.statsd?.timing(`plugin.task.${taskName}.${pluginConfigId}`, timer)
    return response
}

function getPluginsForTeam(server: PluginsServer, teamId: number): PluginConfig[] {
    return server.pluginConfigsPerTeam.get(teamId) || []
}
