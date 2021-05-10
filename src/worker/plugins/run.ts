import { PluginEvent } from '@posthog/plugin-scaffold'

import { PluginConfig, PluginsServer, PluginTaskType } from '../../types'
import { processError } from '../../utils/db/error'

export async function runOnEvent(server: PluginsServer, event: PluginEvent): Promise<void> {
    const pluginsToRun = getPluginsForTeam(server, event.team_id)

    await Promise.all(
        pluginsToRun.map(async (pluginConfig) => {
            const onEvent = await pluginConfig.vm?.getOnEvent()
            if (onEvent) {
                const timer = new Date()
                try {
                    await onEvent(event)
                } catch (error) {
                    await processError(server, pluginConfig, error, event)
                    server.statsd?.increment(`plugin.${pluginConfig.plugin?.name}.on_event.ERROR`)
                }
                server.statsd?.timing(`plugin.${pluginConfig.plugin?.name}.on_event`, timer)
            }
        })
    )
}

export async function runOnSnapshot(server: PluginsServer, event: PluginEvent): Promise<void> {
    const pluginsToRun = getPluginsForTeam(server, event.team_id)

    await Promise.all(
        pluginsToRun.map(async (pluginConfig) => {
            const onSnapshot = await pluginConfig.vm?.getOnSnapshot()
            if (onSnapshot) {
                const timer = new Date()
                try {
                    await onSnapshot(event)
                } catch (error) {
                    await processError(server, pluginConfig, error, event)
                    server.statsd?.increment(`plugin.${pluginConfig.plugin?.name}.on_event.ERROR`)
                }
                server.statsd?.timing(`plugin.${pluginConfig.plugin?.name}.on_event`, timer)
            }
        })
    )
}

export async function runProcessEvent(server: PluginsServer, event: PluginEvent): Promise<PluginEvent | null> {
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
            server.statsd?.timing(`plugin.process_event`, timer, {
                plugin: pluginConfig.plugin?.name ?? '?',
                teamId: event.team_id.toString(),
            })

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

export async function runProcessEventBatch(server: PluginsServer, batch: PluginEvent[]): Promise<PluginEvent[]> {
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
                server.statsd?.timing('plugin.process_event_batch', timer, {
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

export async function runPluginTask(
    server: PluginsServer,
    taskName: string,
    taskType: PluginTaskType,
    pluginConfigId: number,
    payload?: Record<string, any>
): Promise<any> {
    const timer = new Date()
    let response
    const pluginConfig = server.pluginConfigs.get(pluginConfigId)
    try {
        const task = await pluginConfig?.vm?.getTask(taskName, taskType)
        if (!task) {
            throw new Error(
                `Task "${taskName}" not found for plugin "${pluginConfig?.plugin?.name}" with config id ${pluginConfig}`
            )
        }
        response = await (payload ? task?.exec(payload) : task?.exec())
    } catch (error) {
        await processError(server, pluginConfig || null, error)
        server.statsd?.increment(`plugin.task.${taskType}.${taskName}.${pluginConfigId}.ERROR`)
    }
    server.statsd?.timing(`plugin.task.${taskType}.${taskName}.${pluginConfigId}`, timer)
    return response
}

function getPluginsForTeam(server: PluginsServer, teamId: number): PluginConfig[] {
    return server.pluginConfigsPerTeam.get(teamId) || []
}
