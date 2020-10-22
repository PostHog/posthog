import * as path from 'path'
import { Isolate } from 'isolated-vm'
import * as fs from 'fs'
import { Pool } from 'pg'

const db = new Pool({
    connectionString: 'postgres://localhost:5432/posthog',
})

const ROOT_PATH = '../../posthog'

const plugins = {}
const pluginsPerTeam = {}
const pluginVms = {}
const defaultConfigs = []

export async function setupPlugins() {
    const { rows: pluginRows } = await db.query('SELECT * FROM posthog_plugin')
    for (const row of pluginRows) {
        plugins[row.id] = row
        await loadPlugin(row)
    }

    const { rows: pluginConfigRows } = await db.query("SELECT * FROM posthog_pluginconfig WHERE enabled='t'")
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

async function loadPlugin(plugin) {
    if (plugin.url.startsWith('file:')) {
        const pluginPath = path.resolve(ROOT_PATH, plugin.url.substring(5))
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

        if (!config['jsmain']) {
            console.error(`No "jsmain" key found in plugin.json for plugin "${plugin.name}"`)
            return
        }

        const jsPath = path.resolve(pluginPath, config['jsmain'])
        const indexJs = fs.readFileSync(jsPath).toString()

        pluginVms[plugin.id] = {
            plugin,
            indexJs,
            vm: await createVm(plugin, indexJs),
        }

        console.log(`Loaded plugin "${plugin.name}"!`)
    } else {
        console.error('Github plugins not yet supported')
    }
}

async function createVm(plugin, indexJs: string) {
    const isolate = new Isolate({ memoryLimit: 128 })
    const context = isolate.createContextSync()
    const jail = context.global
    jail.setSync('global', jail.derefInto())

    // We will create a basic `log` function for the new isolate to use.
    const logCallback = function (...args) {
        console.log(...args)
    }
    context.evalClosureSync(
        `global.log = function(...args) {
        $0.applyIgnored(undefined, args, { arguments: { copy: true } });
    }`,
        [logCallback],
        { arguments: { reference: true } }
    )

    await context.eval(indexJs)
    const processEvent = await context.global.get('process_event')

    return {
        isolate,
        context,
        processEvent: await context.global.get('process_event'),
        processCapture: await context.global.get('process_capture'),
        processIdentify: await context.global.get('process_identify'),
    }
}

export async function runPlugins(event) {
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
            }
            const { processEvent } = pluginVms[teamPlugin.plugin_id].vm
            try {
                const response = await processEvent.apply(
                    undefined,
                    [returnedEvent, meta],
                    { result: { promise: true, copy: true }, arguments: { copy: true } }
                )
                returnedEvent = response
            } catch (error) {
                console.error(error)
            }

            if (!returnedEvent) {
                return null
            }
        }
    }

    return returnedEvent
}
