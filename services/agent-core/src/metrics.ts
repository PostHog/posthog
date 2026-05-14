import { Registry, collectDefaultMetrics } from 'prom-client'

/**
 * Process-local Prom registry for the agent runtime. Each process (ingress / runner)
 * uses this registry and exposes /metrics from it.
 *
 * We deliberately do not use the default global registry to avoid cross-talk with any
 * library that registers default metrics at import time.
 */
export const registry = new Registry()

let defaultsCollected = false

export function collectDefaults(): void {
    if (defaultsCollected) {
        return
    }
    collectDefaultMetrics({ register: registry })
    defaultsCollected = true
}

export async function metricsText(): Promise<string> {
    return registry.metrics()
}

export function metricsContentType(): string {
    return registry.contentType
}
