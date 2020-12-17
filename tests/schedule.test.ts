import { setupPiscina } from './helpers/worker'
import { createServer } from '../src/server'
import { runTasksDebounced, startSchedule, waitForTasksToFinish } from '../src/services/schedule'
import { LogLevel } from '../src/types'
import { delay } from '../src/utils'
import { PluginEvent } from '@posthog/plugin-scaffold/src/types'

jest.mock('../src/sql')
jest.setTimeout(60000) // 60 sec timeout

function createEvent(index = 0): PluginEvent {
    return {
        distinct_id: 'my_id',
        ip: '127.0.0.1',
        site_url: 'http://localhost',
        team_id: 2,
        now: new Date().toISOString(),
        event: 'default event',
        properties: { key: 'value', index },
    }
}

test('runTasksDebounced', async () => {
    const workerThreads = 2
    const testCode = `
        const counterKey = 'test_counter_2'
        async function setupPlugin (meta) {
            await meta.cache.set(counterKey, 0)
        } 
        async function processEvent (event, meta) {
            event.properties['counter'] = await meta.cache.get(counterKey)
            return event 
        }
        async function runEveryMinute (meta) {
            // stall for a second
            await new Promise(resolve => __jestSetTimeout(resolve, 500))
            await meta.cache.incr(counterKey)
        }
    `
    const piscina = setupPiscina(workerThreads, testCode, 10)

    const getPluginSchedule = () => piscina.runTask({ task: 'getPluginSchedule' })
    const processEvent = (event: PluginEvent) => piscina.runTask({ task: 'processEvent', args: { event } })

    const [server, closeServer] = await createServer({ LOG_LEVEL: LogLevel.Log })
    server.pluginSchedule = await getPluginSchedule()
    expect(server.pluginSchedule).toEqual({ runEveryDay: [], runEveryHour: [], runEveryMinute: [39] })

    const event1 = await processEvent(createEvent())
    expect(event1.properties['counter']).toBe(0)

    runTasksDebounced(server, piscina, 'runEveryMinute')
    runTasksDebounced(server, piscina, 'runEveryMinute')
    runTasksDebounced(server, piscina, 'runEveryMinute')
    await delay(100)

    const event2 = await processEvent(createEvent())
    expect(event2.properties['counter']).toBe(0)

    await delay(500)

    const event3 = await processEvent(createEvent())
    expect(event3.properties['counter']).toBe(1)

    await waitForTasksToFinish(server)
    await piscina.destroy()
    await closeServer()
})

test('runTasksDebounced exception', async () => {
    const workerThreads = 2
    const testCode = `
        async function runEveryMinute (meta) {
            throw new Error('lol')
        }
    `
    const piscina = setupPiscina(workerThreads, testCode, 10)

    const getPluginSchedule = () => piscina.runTask({ task: 'getPluginSchedule' })
    const [server, closeServer] = await createServer({ LOG_LEVEL: LogLevel.Log })
    server.pluginSchedule = await getPluginSchedule()

    runTasksDebounced(server, piscina, 'runEveryMinute')

    await waitForTasksToFinish(server)

    // nothing bad should have happened. the error is in SQL via setError, but that ran in another worker (can't mock)
    // and we're not testing it E2E so we can't check the DB either...

    await piscina.destroy()
    await closeServer()
})

test('redlock', async () => {
    const workerThreads = 2
    const testCode = `
        async function runEveryMinute (meta) {
            throw new Error('lol')
        }
    `
    const piscina = setupPiscina(workerThreads, testCode, 10)
    const [server, closeServer] = await createServer({ LOG_LEVEL: LogLevel.Log, SCHEDULE_LOCK_TTL: 3 })

    let lock1 = false
    let lock2 = false
    let lock3 = false

    const stopSchedule1 = await startSchedule(server, piscina, () => {
        lock1 = true
    })
    const stopSchedule2 = await startSchedule(server, piscina, () => {
        lock2 = true
    })
    const stopSchedule3 = await startSchedule(server, piscina, () => {
        lock3 = true
    })

    await delay(1500)

    expect(lock1).toBe(true)
    expect(lock2).toBe(false)
    expect(lock3).toBe(false)

    await stopSchedule1()

    await delay(1500)

    expect(lock2 || lock3).toBe(true)

    if (lock3) {
        await stopSchedule3()
        await delay(1000)
        expect(lock2).toBe(true)
        await stopSchedule2()
    } else {
        await stopSchedule2()
        await delay(1000)
        expect(lock3).toBe(true)
        await stopSchedule3()
    }

    await piscina.destroy()
    await closeServer()
})

test('unobtained redlock does not leave itself hanging', async () => {
    const workerThreads = 2
    const testCode = `
        async function runEveryMinute (meta) {
            throw new Error('lol')
        }
    `
    const [server, closeServer] = await createServer({ LOG_LEVEL: LogLevel.Log, SCHEDULE_LOCK_TTL: 3 })
    const piscina = setupPiscina(workerThreads, testCode, 10)

    let lock1 = false
    let lock2 = false

    const stopSchedule1 = await startSchedule(server, piscina, () => {
        lock1 = true
    })
    const stopSchedule2 = await startSchedule(server, piscina, () => {
        lock2 = true
    })

    await delay(1500)

    expect(lock1).toBe(true)
    expect(lock2).toBe(false)

    await stopSchedule1()
    await stopSchedule2()

    await piscina.destroy()
    await closeServer()
})
