import { createNodeService, type HealthCheck, type LogLevel, type NodeService } from '@posthog/node-service'

import type { CounterStore } from './features/counters/counter-store.js'
import { registerCounterRoutes } from './features/counters/routes.js'

export interface CreateAppOptions {
    store: CounterStore
    postgresReadiness: HealthCheck
    logLevel?: LogLevel
}

export function createApp(options: CreateAppOptions): NodeService {
    const service = createNodeService({
        name: 'node-service-demo',
        ...(options.logLevel ? { logLevel: options.logLevel } : {}),
        readinessChecks: {
            postgres: options.postgresReadiness,
        },
    })

    registerCounterRoutes(service.app, options.store)

    return service
}
