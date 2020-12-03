import * as path from 'path'
import * as fs from 'fs'
import { createPluginConfigVM, prepareForRun } from './vm'
import { PluginsServer, Plugin, PluginConfig, PluginJsonConfig, PluginId, PluginConfigId, TeamId } from './types'
import { PluginEvent, PluginAttachment } from 'posthog-plugins'
import { clearError, processError } from './error'
import { getFileFromArchive } from './utils'
import { performance } from 'perf_hooks'
import { logTime } from './stats'
import { getPluginAttachmentRows, getPluginConfigRows, getPluginRows } from './sql'

const plugins = new Map<PluginId, Plugin>()
const pluginConfigs = new Map<PluginConfigId, PluginConfig>()
const pluginConfigsPerTeam = new Map<TeamId, PluginConfig[]>()
let defaultConfigs: PluginConfig[] = []

export async function setupPlugins(
    server: PluginsServer
): Promise<{
    plugins: Map<PluginId, Plugin>
    pluginConfigs: Map<PluginConfigId, PluginConfig>
    pluginConfigsPerTeam: Map<TeamId, PluginConfig[]>
    defaultConfigs: PluginConfig[]
}> {
    const pluginRows = await getPluginRows(server)
    const foundPlugins = new Map<number, boolean>()
    for (const row of pluginRows) {
        foundPlugins.set(row.id, true)
        plugins.set(row.id, row)
    }
    for (const [id, plugin] of plugins) {
        if (!foundPlugins.has(id)) {
            plugins.delete(id)
        }
    }

    const pluginAttachmentRows = await getPluginAttachmentRows(server)
    const attachmentsPerConfig = new Map<TeamId, Record<string, PluginAttachment>>()
    for (const row of pluginAttachmentRows) {
        let attachments = attachmentsPerConfig.get(row.plugin_config_id)
        if (!attachments) {
            attachments = {}
            attachmentsPerConfig.set(row.plugin_config_id, attachments)
        }
        attachments[row.key] = {
            content_type: row.content_type,
            file_name: row.file_name,
            contents: row.contents,
        }
    }

    const pluginConfigRows = await getPluginConfigRows(server)
    const foundPluginConfigs = new Map<number, boolean>()
    pluginConfigsPerTeam.clear()
    defaultConfigs = []
    for (const row of pluginConfigRows) {
        const plugin = plugins.get(row.plugin_id)
        if (!plugin) {
            continue
        }
        foundPluginConfigs.set(row.id, true)
        const pluginConfig: PluginConfig = {
            ...row,
            plugin: plugin,
            attachments: attachmentsPerConfig.get(row.id) || {},
            vm: null,
        }
        pluginConfigs.set(row.id, pluginConfig)

        if (!row.team_id) {
            defaultConfigs.push(row)
        } else {
            let teamConfigs = pluginConfigsPerTeam.get(row.team_id)
            if (!teamConfigs) {
                teamConfigs = []
                pluginConfigsPerTeam.set(row.team_id, teamConfigs)
            }
            teamConfigs.push(pluginConfig)
        }
    }
    for (const [id, pluginConfig] of pluginConfigs) {
        if (!foundPluginConfigs.has(id)) {
            pluginConfigs.delete(id)
        } else if (!pluginConfig.vm) {
            await loadPlugin(server, pluginConfig)
        }
    }

    if (defaultConfigs.length > 0) {
        defaultConfigs.sort((a, b) => a.order - b.order)
        for (const teamId of Object.keys(pluginConfigsPerTeam).map((key: string) => parseInt(key))) {
            pluginConfigsPerTeam.set(teamId, [...(pluginConfigsPerTeam.get(teamId) || []), ...defaultConfigs])
            pluginConfigsPerTeam.get(teamId)?.sort((a, b) => a.id - b.id)
        }
    }

    return {
        plugins,
        pluginConfigs,
        pluginConfigsPerTeam,
        defaultConfigs,
    }
}

async function loadPlugin(server: PluginsServer, pluginConfig: PluginConfig): Promise<boolean> {
    const { plugin } = pluginConfig

    if (!plugin) {
        return false
    }

    try {
        if (plugin.url.startsWith('file:')) {
            const pluginPath = path.resolve(server.BASE_DIR, plugin.url.substring(5))
            const configPath = path.resolve(pluginPath, 'plugin.json')

            let config: PluginJsonConfig = {}
            if (fs.existsSync(configPath)) {
                try {
                    const jsonBuffer = fs.readFileSync(configPath)
                    config = JSON.parse(jsonBuffer.toString())
                } catch (e) {
                    await processError(
                        server,
                        pluginConfig,
                        `Could not load posthog config at "${configPath}" for plugin "${plugin.name}"`
                    )
                    return false
                }
            }

            if (!config['main'] && !fs.existsSync(path.resolve(pluginPath, 'index.js'))) {
                await processError(
                    server,
                    pluginConfig,
                    `No "main" config key or "index.js" file found for plugin "${plugin.name}"`
                )
                return false
            }

            const jsPath = path.resolve(pluginPath, config['main'] || 'index.js')
            const indexJs = fs.readFileSync(jsPath).toString()

            const libPath = path.resolve(pluginPath, config['lib'] || 'lib.js')
            const libJs = fs.existsSync(libPath) ? fs.readFileSync(libPath).toString() : ''
            if (libJs) {
                console.warn(`⚠️ Using "lib.js" is deprecated! Used by: ${plugin.name} (${plugin.url})`)
            }

            try {
                pluginConfig.vm = createPluginConfigVM(server, pluginConfig, indexJs, libJs)
                console.log(`Loaded local plugin "${plugin.name}" from "${pluginPath}"!`)
                await clearError(server, pluginConfig)
                return true
            } catch (error) {
                await processError(server, pluginConfig, error)
            }
        } else if (plugin.archive) {
            let config: PluginJsonConfig = {}
            const json = await getFileFromArchive(plugin.archive, 'plugin.json')
            if (json) {
                try {
                    config = JSON.parse(json)
                } catch (error) {
                    await processError(server, pluginConfig, `Can not load plugin.json for plugin "${plugin.name}"`)
                    return false
                }
            }

            const indexJs = await getFileFromArchive(plugin.archive, config['main'] || 'index.js')
            const libJs = await getFileFromArchive(plugin.archive, config['lib'] || 'lib.js')
            if (libJs) {
                console.warn(`⚠️ Using "lib.js" is deprecated! Used by: ${plugin.name} (${plugin.url})`)
            }

            if (indexJs) {
                try {
                    pluginConfig.vm = createPluginConfigVM(server, pluginConfig, indexJs, libJs || '')
                    console.log(`Loaded plugin "${plugin.name}"!`)
                    await clearError(server, pluginConfig)
                    return true
                } catch (error) {
                    await processError(server, pluginConfig, error)
                }
            } else {
                await processError(server, pluginConfig, `Could not load index.js for plugin "${plugin.name}"!`)
            }
        } else {
            await processError(server, pluginConfig, 'Un-downloaded remote plugins not supported!')
        }
    } catch (error) {
        await processError(server, pluginConfig, error)
    }
    return false
}

export async function runPlugins(server: PluginsServer, event: PluginEvent): Promise<PluginEvent | null> {
    const pluginsToRun = pluginConfigsPerTeam.get(event.team_id) || defaultConfigs

    let returnedEvent: PluginEvent | null = event

    for (const pluginConfig of pluginsToRun.reverse()) {
        if (pluginConfig.vm) {
            const processEvent = prepareForRun(server, event.team_id, pluginConfig, 'processEvent', event)

            if (processEvent) {
                const startTime = performance.now()
                try {
                    returnedEvent = (await processEvent(returnedEvent)) || null
                    const ms = Math.round((performance.now() - startTime) * 1000) / 1000
                    logTime(pluginConfig.plugin?.name || 'noname', ms)
                } catch (error) {
                    await processError(server, pluginConfig, error, returnedEvent)
                    const ms = Math.round((performance.now() - startTime) * 1000) / 1000
                    logTime(pluginConfig.plugin?.name || 'noname', ms, true)
                }
            }

            if (!returnedEvent) {
                return null
            }
        }
    }

    return returnedEvent
}
