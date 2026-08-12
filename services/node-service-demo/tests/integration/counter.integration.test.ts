import { createApp } from '../../src/app.js'
import { isPostgresReady } from '../../src/infrastructure/postgres/pool.js'
import { createTestStore, type TestStore } from '../helpers/database.js'

describe('counter API with Postgres', () => {
    let testStore: TestStore

    beforeAll(async () => {
        testStore = await createTestStore()
    })

    afterAll(async () => {
        await testStore.close()
    })

    it('persists increments across requests after applying migrations', async () => {
        const service = createApp({
            store: testStore.store,
            postgresReadiness: async () =>
                (await isPostgresReady(testStore.pool)) ? { status: 'ok' } : { status: 'error' },
            logLevel: 'error',
        })
        const incrementUrl = `/api/counters/${testStore.counterName}/increment`
        const readUrl = `/api/counters/${testStore.counterName}`

        const firstIncrement = await service.app.request(incrementUrl, { method: 'POST' })
        const secondIncrement = await service.app.request(incrementUrl, { method: 'POST' })
        const read = await service.app.request(readUrl)

        expect(firstIncrement.status).toBe(200)
        expect(await firstIncrement.json()).toEqual({ name: testStore.counterName, value: 1 })
        expect(await secondIncrement.json()).toEqual({ name: testStore.counterName, value: 2 })
        expect(await read.json()).toEqual({ name: testStore.counterName, value: 2 })
    })
})
