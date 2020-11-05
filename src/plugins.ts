import * as path from 'path'
import * as fs from 'fs'
import { createVm, prepareForRun } from './vm'
import { PluginsServer, Plugin, PluginConfig, PluginVM } from './types'
import { PluginEvent } from 'posthog-plugins'
import { clearError, processError } from './error'
import { getFileFromArchive } from './utils'

const plugins: Record<string, Plugin> = {}
const pluginsPerTeam: Record<string, PluginConfig[]> = {}
const pluginVms: Record<string, PluginVM> = {}
const defaultConfigs: PluginConfig[] = []

export async function setupPlugins(server: PluginsServer) {
    const { rows: pluginRows }: { rows: Plugin[] } = await server.db.query(
        "SELECT * FROM posthog_plugin WHERE (select count(*) from posthog_pluginconfig where plugin_id = posthog_plugin.id and enabled='t') > 0"
    )
    const foundPlugins: Record<string, boolean> = {}
    for (const row of pluginRows) {
        foundPlugins[row.id] = true
        if (
            !plugins[row.id] ||
            row.url.startsWith('file:') ||
            row.tag !== plugins[row.id].tag ||
            row.name !== plugins[row.id].name ||
            row.url !== plugins[row.id].url
        ) {
            if (plugins[row.id]) {
                unloadPlugin(row)
            }
            plugins[row.id] = row
            await loadPlugin(server, row)
        }
    }
    for (const id of Object.keys(plugins)) {
        if (!foundPlugins[id]) {
            unloadPlugin(plugins[id])
        }
    }

    const { rows: pluginConfigRows }: { rows: PluginConfig[] } = await server.db.query(
        "SELECT * FROM posthog_pluginconfig WHERE enabled='t'"
    )
    for (const row of pluginConfigRows) {
        if (!row.team_id) {
            defaultConfigs.push(row)
        } else {
            if (!pluginsPerTeam[row.team_id]) {
                pluginsPerTeam[row.team_id] = []
            }
            pluginsPerTeam[row.team_id].push(row)
        }

        const setupTeam = prepareForRun(
            server,
            pluginVms[row.plugin_id],
            row.team_id,
            row,
            'setupTeam',
            undefined
        ) as () => void

        if (setupTeam) {
            await setupTeam()
        }
    }

    if (defaultConfigs.length > 0) {
        defaultConfigs.sort((a, b) => a.order - b.order)
        for (const teamId of Object.keys(pluginsPerTeam)) {
            pluginsPerTeam[teamId] = [...pluginsPerTeam[teamId], ...defaultConfigs]
            pluginsPerTeam[teamId].sort((a, b) => a.order - b.order)
        }
    }
}

function unloadPlugin(plugin: Plugin) {
    delete plugins[plugin.id]
    delete pluginVms[plugin.id]
}

async function loadPlugin(server: PluginsServer, plugin: Plugin) {
    if (plugin.url.startsWith('file:')) {
        const pluginPath = path.resolve(server.BASE_DIR, plugin.url.substring(5))
        const configPath = path.resolve(pluginPath, 'plugin.json')

        let config: Record<string, any> = {}
        if (fs.existsSync(configPath)) {
            try {
                const jsonBuffer = fs.readFileSync(configPath)
                config = JSON.parse(jsonBuffer.toString())
            } catch (e) {
                await processError(
                    server,
                    plugin,
                    null,
                    `Could not load posthog config at "${configPath}" for plugin "${plugin.name}"`
                )
                return
            }
        }

        if (!config['main'] && !fs.existsSync(path.resolve(pluginPath, 'index.js'))) {
            await processError(
                server,
                plugin,
                null,
                `No "main" config key or "index.js" file found for plugin "${plugin.name}"`
            )
            return
        }

        const jsPath = path.resolve(pluginPath, config['main'] || 'index.js')
        const indexJs = fs.readFileSync(jsPath).toString()

        const libPath = path.resolve(pluginPath, config['lib'] || 'lib.js')
        const libJs = fs.existsSync(libPath) ? fs.readFileSync(libPath).toString() : ''

        try {
            pluginVms[plugin.id] = {
                plugin,
                indexJs,
                libJs,
                ...(await createVm(plugin, indexJs, libJs, server)),
            }
            console.log(`Loaded local plugin "${plugin.name}" from "${pluginPath}"!`)
            await clearError(server, plugin, null)
        } catch (error) {
            await processError(server, plugin, null, error)
        }
    } else if (plugin.archive) {
        let config: Record<string, any> = {}
        const json = await getFileFromArchive(plugin.archive, 'plugin.json')
        if (json) {
            try {
                config = JSON.parse(json)
            } catch (error) {
                await processError(server, plugin, null, `Can not load plugin.json for plugin "${plugin.name}"`)
            }
        }

        const indexJs = await getFileFromArchive(plugin.archive, config['main'] || 'index.js')
        const libJs = await getFileFromArchive(plugin.archive, config['lib'] || 'lib.js')

        if (indexJs) {
            try {
                pluginVms[plugin.id] = {
                    plugin,
                    indexJs,
                    libJs,
                    ...(await createVm(plugin, indexJs, libJs, server)),
                }
                console.log(`Loaded plugin "${plugin.name}"!`)
                await clearError(server, plugin, null)
            } catch (error) {
                await processError(server, plugin, null, error)
            }
        } else {
            await processError(server, plugin, null, `Could not load index.js for plugin "${plugin.name}"!`)
        }
    } else {
        console.error('Undownloaded Github plugins not yet supported')
    }
}

export async function runPlugins(server: PluginsServer, event: PluginEvent) {
    const teamId = event.team_id
    const pluginsToRun = pluginsPerTeam[teamId] || defaultConfigs

    let returnedEvent: PluginEvent | null = event

    for (const teamPlugin of pluginsToRun) {
        if (pluginVms[teamPlugin.plugin_id]) {
            const processEvent = prepareForRun(
                server,
                pluginVms[teamPlugin.plugin_id],
                teamId,
                teamPlugin,
                'processEvent',
                event
            )

            if (processEvent) {
                try {
                    returnedEvent = (await processEvent(returnedEvent)) || null
                } catch (error) {
                    await processError(server, plugins[teamPlugin.plugin_id], teamPlugin, error, returnedEvent)
                }
            }

            if (!returnedEvent) {
                return null
            }
        }
    }

    return returnedEvent
}
