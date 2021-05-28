import { PluginEvent } from '@posthog/plugin-scaffold'

import { Hub, PluginConfig, PluginTaskType } from '../../types'
import { processError } from '../../utils/db/error'

export class IllegalOperationError extends Error {
    name = 'IllegalOperationError'

    constructor(operation: string) {
        super(operation)
    }
}

export async function runOnEvent(server: Hub, event: PluginEvent): Promise<void> {
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

export async function runOnSnapshot(server: Hub, event: PluginEvent): Promise<void> {
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

export async function runProcessEvent(server: Hub, event: PluginEvent): Promise<PluginEvent | null> {
    const teamId = event.team_id
    const pluginsToRun = getPluginsForTeam(server, teamId)
    let returnedEvent: PluginEvent | null = event

    const pluginsSucceeded = []
    const pluginsFailed = []
    for (const pluginConfig of pluginsToRun) {
        const processEvent = await pluginConfig.vm?.getProcessEvent()

        if (processEvent) {
            const timer = new Date()

            try {
                returnedEvent = (await processEvent(returnedEvent)) || null
                if (returnedEvent && returnedEvent.team_id !== teamId) {
                    returnedEvent.team_id = teamId
                    throw new IllegalOperationError('Plugin tried to change event.team_id')
                }
                pluginsSucceeded.push(`${pluginConfig.plugin?.name} (${pluginConfig.id})`)
            } catch (error) {
                await processError(server, pluginConfig, error, returnedEvent)
                server.statsd?.increment(`plugin.${pluginConfig.plugin?.name}.process_event.ERROR`)
                pluginsFailed.push(`${pluginConfig.plugin?.name} (${pluginConfig.id})`)
            }
            server.statsd?.timing(`plugin.process_event`, timer, {
                plugin: pluginConfig.plugin?.name ?? '?',
                teamId: teamId.toString(),
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

export async function runPluginTask(
    server: Hub,
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

function getPluginsForTeam(server: Hub, teamId: number): PluginConfig[] {
    return server.pluginConfigsPerTeam.get(teamId) || []
}
