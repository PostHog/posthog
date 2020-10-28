import * as path from 'path'
import * as fs from 'fs'
import { Pool } from 'pg'
import { createInternalPostHogInstance } from 'posthog-js-lite'
import fetch from 'node-fetch'
import { createVm } from './vm'
import { PluginsServer } from './types'
import { createCache } from './extensions/cache'
import AdmZip from 'adm-zip'

const plugins = {}
const pluginsPerTeam = {}
const pluginVms = {}
const defaultConfigs = []

export async function processError(error: Error) {
    // TODO: save in database
    // TODO: send to sentry
    console.error(error)
}

export async function setupPlugins(server: PluginsServer) {
    const { rows: pluginRows } = await server.db.query("SELECT * FROM posthog_plugin WHERE (select count(*) from posthog_pluginconfig where plugin_id = posthog_plugin.id and enabled='t') > 0")
    const foundPlugins = {}
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

    const { rows: pluginConfigRows } = await server.db.query("SELECT * FROM posthog_pluginconfig WHERE enabled='t'")
    for (const row of pluginConfigRows) {
        if (!row.team_id) {
            defaultConfigs.push(row)
        } else {
            if (!pluginsPerTeam[row.team_id]) {
                pluginsPerTeam[row.team_id] = []
            }
            pluginsPerTeam[row.team_id].push(row)
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

function unloadPlugin(plugin) {
    delete plugins[plugin.id]
    delete pluginVms[plugin.id]
}

async function loadPlugin(server: PluginsServer, plugin) {
    if (plugin.url.startsWith('file:')) {
        const pluginPath = path.resolve(server.BASE_DIR, plugin.url.substring(5))
        const configPath = path.resolve(pluginPath, 'plugin.json')

        let config = {}
        if (fs.existsSync(configPath)) {
            try {
                const jsonBuffer = fs.readFileSync(configPath)
                config = JSON.parse(jsonBuffer.toString())
            } catch (e) {
                console.error(`Could not load posthog config at "${configPath}" for plugin "${plugin.name}"`)
                return
            }
        }

        if (!config['main'] && !fs.existsSync(path.resolve(pluginPath, 'index.js'))) {
            console.error(`No "main" config key or "index.js" file found for plugin "${plugin.name}"`)
            return
        }

        const jsPath = path.resolve(pluginPath, config['main'] || 'index.js')
        const indexJs = fs.readFileSync(jsPath).toString()

        const libPath = path.resolve(pluginPath, config['lib'] || 'lib.js')
        const libJs = fs.existsSync(libPath) ? fs.readFileSync(libPath).toString() : ''

        pluginVms[plugin.id] = {
            plugin,
            indexJs,
            libJs,
            vm: await createVm(plugin, indexJs, libJs, server),
        }

        console.log(`Loaded local plugin "${plugin.name}" from "${pluginPath}"!`)
    } else if (plugin.archive) {
        const zip = new AdmZip(plugin.archive)
        const zipEntries = zip.getEntries() // an array of ZipEntry records
        const root = zipEntries[0].entryName

        let config = {}
        const json = zip.getEntry(`${root}plugin.json`)
        if (json) {
            try {
                config = JSON.parse(json.getData().toString())
            } catch (error) {
                console.error(`Can not load plugin.json for plugin "${plugin.name}"`)
                console.error(error)
            }
        }

        const indexEntry = zip.getEntry(`${root}${json['main'] || 'index.js'}`)
        const indexJs = indexEntry ? indexEntry.getData().toString() : null

        const libEntry = zip.getEntry(`${root}${json['lib'] || 'lib.js'}`)
        const libJs = libEntry ? libEntry.getData().toString() : null

        pluginVms[plugin.id] = {
            plugin,
            indexJs,
            libJs,
            vm: await createVm(plugin, indexJs, libJs, server),
        }

        console.log(`Loaded plugin "${plugin.name}"!`)
    } else {
        console.error('Undownloaded Github plugins not yet supported')
    }
}

export async function runPlugins(server: PluginsServer, event) {
    const teamId = event.team_id
    const pluginsToRun = pluginsPerTeam[teamId] || defaultConfigs

    let returnedEvent = event

    for (const teamPlugin of pluginsToRun) {
        if (pluginVms[teamPlugin.plugin_id]) {
            const plugin = plugins[teamPlugin.plugin_id]
            const meta = {
                team: teamPlugin.team_id,
                order: teamPlugin.order,
                name: plugin.name,
                tag: plugin.tag,
                config: teamPlugin.config,
                apiKey: teamPlugin.api_token,
            }
            const { vm, processEvent } = pluginVms[teamPlugin.plugin_id].vm

            vm.freeze(createCache(server, plugin.name, teamId), 'cache')

            if (event?.properties?.token) {
                const posthog = createInternalPostHogInstance(
                    event.properties.token,
                    { apiHost: event.site_url, fetch },
                    {
                        performance: require('perf_hooks').performance,
                    }
                )
                vm.freeze(posthog, 'posthog')
            } else {
                vm.freeze(null, 'posthog')
            }

            if (processEvent) {
                try {
                    returnedEvent = await processEvent(returnedEvent, meta)
                } catch (error) {
                    processError(error)
                }
            }

            if (!returnedEvent) {
                return null
            }
        }
    }

    return returnedEvent
}
