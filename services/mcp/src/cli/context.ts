import { createHash, randomUUID } from 'node:crypto'

import { ApiClient } from '@/api/client'
import { MemoryCache } from '@/lib/cache/MemoryCache'
import { getPostHogClient } from '@/lib/posthog'
import { buildMCPAnalyticsGroups, buildMCPContextProperties } from '@/lib/posthog/analytics'
import type { AnalyticsEvent } from '@/lib/posthog/analytics'
import { SessionManager } from '@/lib/SessionManager'
import { StateManager } from '@/lib/StateManager'
import type { Context, Env, State } from '@/tools/types'

import type { CliConfig } from './config'

function cliIdentityKey(apiKey: string | undefined): string {
    if (!apiKey) {
        return 'anonymous'
    }
    return createHash('sha256').update(apiKey).digest('hex').slice(0, 16)
}

const pendingAnalytics = new Set<Promise<void>>()

/**
 * Flush queued analytics before the process exits. `process.exit()` does not
 * wait for in-flight requests, so the error path must call this explicitly —
 * without it, errored `$mcp_tool_call` events are enqueued but never sent.
 */
export async function flushAnalytics(timeoutMs = 2000): Promise<void> {
    try {
        await Promise.race([
            Promise.allSettled([...pendingAnalytics]),
            new Promise((resolve) => setTimeout(resolve, timeoutMs).unref()),
        ])
        await getPostHogClient().shutdown(timeoutMs)
    } catch {
        // Analytics must never fail or block the CLI.
    }
}

export async function buildCliContext(config: CliConfig): Promise<Context> {
    const identityKey = cliIdentityKey(config.apiKey)
    const fallbackDistinctId = `posthog-cli:${identityKey}`
    // Set by the Rust wrapper; joins these events to its telemetry for the same run.
    const cliInvocationId = process.env.POSTHOG_CLI_INVOCATION_ID
    const cache = new MemoryCache<State>(`cli:${identityKey}:${config.host}`)
    await cache.setMany({
        ...(config.organizationId ? { orgId: config.organizationId } : {}),
        ...(config.projectId ? { projectId: config.projectId } : {}),
    })

    const api = new ApiClient({
        apiToken: config.apiKey ?? '',
        baseUrl: config.host.replace(/\/+$/, ''),
        clientUserAgent: `posthog-cli api`,
        mcpClientName: 'posthog-cli',
        mcpClientVersion: process.env.POSTHOG_CLI_VERSION,
        mcpConsumer: 'posthog-cli',
    })
    const stateManager = new StateManager(cache, api)
    const sessionManager = new SessionManager(cache)
    const sessionId = randomUUID()

    const context: Context = {
        api,
        cache,
        env: process.env as Env,
        stateManager,
        sessionManager,
        getDistinctId: () => stateManager.getDistinctId(),
        trackEvent: (event: AnalyticsEvent, properties: Record<string, unknown> = {}) => {
            const capture = (async (): Promise<void> => {
                try {
                    const [distinctId, analyticsContext] = await Promise.all([
                        stateManager.getDistinctId().catch(() => undefined),
                        stateManager.getAnalyticsContext().catch(() => undefined),
                    ])
                    const groups = analyticsContext ? buildMCPAnalyticsGroups(analyticsContext) : {}

                    getPostHogClient().capture({
                        distinctId: distinctId ?? fallbackDistinctId,
                        event,
                        ...(Object.keys(groups).length > 0 ? { groups } : {}),
                        properties: {
                            $ai_product: 'mcp',
                            $mcp_source: 'posthog_cli',
                            $mcp_client_name: 'posthog-cli',
                            $mcp_consumer: 'posthog-cli',
                            $mcp_mode: 'cli',
                            $mcp_version: config.version,
                            ...(cliInvocationId ? { cli_invocation_id: cliInvocationId } : {}),
                            ...(analyticsContext ? buildMCPContextProperties(analyticsContext) : {}),
                            $session_id: await sessionManager.getSessionUuid(sessionId),
                            ...properties,
                        },
                    })
                } catch {}
            })()
            pendingAnalytics.add(capture)
            void capture.finally(() => pendingAnalytics.delete(capture))
            return capture
        },
    }

    return context
}
