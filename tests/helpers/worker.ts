import Piscina from 'piscina'
import { makePiscina } from '../../src/worker/piscina'
import { defaultConfig } from '../../src/config'
import { LogLevel } from '../../src/types'
import { mockJestWithIndex } from './plugins'

export function setupPiscina(workers: number, code: string, tasksPerWorker: number): Piscina {
    return makePiscina({
        ...defaultConfig,
        WORKER_CONCURRENCY: workers,
        TASKS_PER_WORKER: tasksPerWorker,
        LOG_LEVEL: LogLevel.Log,
        __jestMock: mockJestWithIndex(code),
    })
}
