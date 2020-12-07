import { defaultConfig } from '../src/server'
import { makePiscina } from '../src/worker/piscina'
import { PluginEvent } from 'posthog-plugins/src/types'
import { performance } from 'perf_hooks'
import { mockJestWithIndex } from './helpers/plugins'
import * as os from 'os'

jest.mock('../src/sql')
jest.setTimeout(300000) // 300 sec timeout

function processOneEvent(processEvent: (event: PluginEvent) => Promise<PluginEvent>): Promise<PluginEvent> {
    const defaultEvent = {
        distinct_id: 'my_id',
        ip: '127.0.0.1',
        site_url: 'http://localhost',
        team_id: 2,
        now: new Date().toISOString(),
        event: 'default event',
        properties: { key: 'value' },
    }

    return processEvent(defaultEvent)
}

async function processCountEvents(count: number, piscina: ReturnType<typeof makePiscina>) {
    const startTime = performance.now()
    const promises = Array(count)
    const processEvent = (event: PluginEvent) => piscina.runTask({ task: 'processEvent', args: { event } })
    for (let i = 0; i < count; i++) {
        promises[i] = processOneEvent(processEvent)
    }
    // this will get heavy for tests > 10k events, should chunk them somehow...
    await Promise.all(promises)

    const ms = Math.round((performance.now() - startTime) * 1000) / 1000

    const log = {
        eventsPerSecond: 1000 / (ms / count),
        events: count,
        concurrency: piscina.threads.length,
        totalMs: ms,
        averageEventMs: ms / count,
    }

    return log
}

function setupPiscina(workers: number, code: string, tasksPerWorker: number) {
    return makePiscina({
        ...defaultConfig,
        WORKER_CONCURRENCY: workers,
        TASKS_PER_WORKER: tasksPerWorker,
        __jestMock: mockJestWithIndex(code),
    })
}

test('piscina worker test', async () => {
    const testName = ''
    const coreCount = os.cpus().length

    const workers = [1, 2, 4, 8].filter((cores) => cores <= coreCount)
    const rounds = 5

    const tests: { testName: string; events: number; testCode: string }[] = [
        {
            testName: 'simple',
            events: 10000,
            testCode: `
                function processEvent (event, meta) {
                    event.properties = { "somewhere": "over the rainbow" };
                    return event
                }
            `,
        },
        {
            testName: 'for200k',
            events: 10000,
            testCode: `
                function processEvent (event, meta) {
                    let j = 0; for(let i = 0; i < 200000; i++) { j = i };
                    event.properties = { "somewhere": "over the rainbow" };
                    return event
                }
            `,
        },
        {
            testName: 'timeout100ms',
            events: 5,
            testCode: `
                async function processEvent (event, meta) {
                    await new Promise(resolve => __jestSetTimeout(() => resolve(), 100))
                    event.properties = { "somewhere": "over the rainbow" };
                    return event             
                }
            `,
        },
    ]

    const results: Array<Record<string, string | number>> = []
    for (const { testName, events, testCode } of tests) {
        const result: Record<string, any> = {
            testName,
            coreCount,
        }
        for (const cores of workers) {
            const piscina = setupPiscina(cores, testCode, 1)

            // warmup
            await processCountEvents(cores * 3, piscina)

            // start
            let throughput = 0
            for (let i = 0; i < rounds; i++) {
                const { eventsPerSecond } = await processCountEvents(events * cores, piscina)
                throughput += eventsPerSecond
            }
            result[`${cores} cores`] = Math.round(throughput / rounds)
            await piscina.destroy()
        }
        results.push(result)
        console.log(JSON.stringify({ result }, null, 2))
    }
    console.table(results)
    // expect that adding more cores (up to coreCount) increases throughput
    // for (let i = 1; i < workers.length; i++) {
    //     expect(result[`${workers[i - 1]} cores`]).toBeLessThan(result[`${workers[i]} cores`])
    // }
})
