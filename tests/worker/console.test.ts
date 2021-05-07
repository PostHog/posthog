import { ConsoleExtension } from '@posthog/plugin-scaffold'

import { PluginLogEntryType, PluginsServer } from '../../src/types'
import { createServer } from '../../src/utils/db/server'
import { getPluginConfigRows } from '../../src/utils/db/sql'
import { createConsole } from '../../src/worker/vm/extensions/console'
import { resetTestDatabase } from '../helpers/sql'

describe('console extension', () => {
    let server: PluginsServer
    let closeServer: () => Promise<void>

    beforeEach(async () => {
        ;[server, closeServer] = await createServer()
        await resetTestDatabase()
    })

    afterEach(async () => {
        await closeServer()
    })

    Object.values(PluginLogEntryType).map((type) => {
        const method = type.toLowerCase() as keyof ConsoleExtension
        describe(`console#${method}`, () => {
            it('leaves an empty entry in the database', async () => {
                const pluginConfig = (await getPluginConfigRows(server))[0]

                const console = createConsole(server, pluginConfig)

                await ((console[method]() as unknown) as Promise<void>)

                const pluginLogEntries = await server.db.fetchPluginLogEntries()

                expect(pluginLogEntries.length).toBe(1)
                expect(pluginLogEntries[0].type).toEqual(type)
                expect(pluginLogEntries[0].message).toEqual('')
            })

            it('leaves a string + number entry in the database', async () => {
                const pluginConfig = (await getPluginConfigRows(server))[0]

                const console = createConsole(server, pluginConfig)

                await ((console[method]('number =', 987) as unknown) as Promise<void>)

                const pluginLogEntries = await server.db.fetchPluginLogEntries()

                expect(pluginLogEntries.length).toBe(1)
                expect(pluginLogEntries[0].type).toEqual(type)
                expect(pluginLogEntries[0].message).toEqual('number = 987')
            })

            it('leaves an error entry in the database', async () => {
                const pluginConfig = (await getPluginConfigRows(server))[0]

                const console = createConsole(server, pluginConfig)

                await ((console[method](new Error('something')) as unknown) as Promise<void>)

                const pluginLogEntries = await server.db.fetchPluginLogEntries()

                expect(pluginLogEntries.length).toBe(1)
                expect(pluginLogEntries[0].type).toEqual(type)
                expect(pluginLogEntries[0].message).toEqual('Error: something')
            })

            it('leaves an object entry in the database', async () => {
                const pluginConfig = (await getPluginConfigRows(server))[0]

                const console = createConsole(server, pluginConfig)

                await ((console[method]({ 1: 'ein', 2: 'zwei' }) as unknown) as Promise<void>)

                const pluginLogEntries = await server.db.fetchPluginLogEntries()

                expect(pluginLogEntries.length).toBe(1)
                expect(pluginLogEntries[0].type).toEqual(type)
                expect(pluginLogEntries[0].message).toEqual(`{"1":"ein","2":"zwei"}`)
            })

            it('leaves an object entry in the database', async () => {
                const pluginConfig = (await getPluginConfigRows(server))[0]

                const console = createConsole(server, pluginConfig)

                await ((console[method]([99, 79]) as unknown) as Promise<void>)

                const pluginLogEntries = await server.db.fetchPluginLogEntries()

                expect(pluginLogEntries.length).toBe(1)
                expect(pluginLogEntries[0].type).toEqual(type)
                expect(pluginLogEntries[0].message).toEqual(`[99,79]`)
            })
        })
    })
})
