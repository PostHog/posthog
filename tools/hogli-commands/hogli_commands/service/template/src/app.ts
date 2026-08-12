import { createNodeService, type LogLevel, type NodeService } from '@posthog/node-service'

import { registerHelloRoutes } from './features/hello/routes.js'

export interface CreateAppOptions {
    logLevel?: LogLevel
}

export function createApp(options: CreateAppOptions = {}): NodeService {
    const service = createNodeService({
        name: '__SERVICE_NAME__',
        ...(options.logLevel ? { logLevel: options.logLevel } : {}),
    })

    registerHelloRoutes(service.app)

    return service
}
