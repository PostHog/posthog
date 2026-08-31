// Side-effect dispatch for the ingest handler.
//
// After each accepted ingest event the handler calls heartbeatWorkflowIfNeeded.
// Redis state mutations (setAgentActive, claimAgentActiveHeartbeat) are awaited
// because they gate the callback decision. The Django HTTP callback is
// fire-and-forget: the fetch result is consumed in a detached promise with
// error logging so failures never propagate into the ingest response.
//
// The Node service stays a pure streaming plane — Temporal signals and Celery
// push notifications go through a single internal Django endpoint. Django
// decides whether a run is interactive; Node always calls the callback and lets
// Django branch on mode.

import type { Config } from './config.js'
import { HEARTBEAT_THROTTLE_SECONDS } from './constants.js'
import { logger } from './logging.js'
import type { TaskRunRedisStream } from './redis-stream.js'
import type { SideEffectKind } from './types.js'

// ACP event field values (byte-identical to ee/hogai/sandbox/types.py)
const ACP_NOTIFICATION_TYPE = 'notification'
const TURN_COMPLETE_METHOD = '_posthog/turn_complete'
const STOP_REASON_END_TURN = 'end_turn'
const ACP_METHOD_SESSION_UPDATE = 'session/update'
const AGENT_COMMAND_DISPATCHED_METHOD = '_posthog/agent_command_dispatched'
const ACP_GENERATION_UPDATES = new Set([
    'agent_message',
    'agent_message_chunk',
    'agent_thought_chunk',
    'tool_call',
    'tool_call_update',
])
const PI_GENERATION_EVENTS = new Set([
    'assistant_message_chunk',
    'assistant_thought_chunk',
    'tool_call_started',
    'tool_call_updated',
])

// isTurnComplete mirrors ee/hogai/sandbox/types.py:is_turn_complete exactly.
// Matches both the raw ACP prompt response (result.stopReason == "end_turn")
// and the synthetic _posthog/turn_complete notification.
export function isTurnComplete(event: Record<string, unknown>): boolean {
    if (event['type'] !== ACP_NOTIFICATION_TYPE) {
        return false
    }
    const notification = event['notification']
    if (typeof notification !== 'object' || notification === null) {
        return false
    }
    const notif = notification as Record<string, unknown>
    if (notif['method'] === TURN_COMPLETE_METHOD) {
        return true
    }
    const result = notif['result']
    return (
        typeof result === 'object' &&
        result !== null &&
        (result as Record<string, unknown>)['stopReason'] === STOP_REASON_END_TURN
    )
}

// isSessionUpdate mirrors event_ingest.py:_is_session_update exactly.
export function isSessionUpdate(event: Record<string, unknown>): boolean {
    if (event['type'] !== ACP_NOTIFICATION_TYPE) {
        return false
    }
    const notification = event['notification']
    if (typeof notification !== 'object' || notification === null) {
        return false
    }
    return (notification as Record<string, unknown>)['method'] === ACP_METHOD_SESSION_UPDATE
}

export function isAgentCommandDispatched(event: Record<string, unknown>): boolean {
    if (event['type'] !== ACP_NOTIFICATION_TYPE) {
        return false
    }
    const notification = event['notification']
    return (
        typeof notification === 'object' &&
        notification !== null &&
        (notification as Record<string, unknown>)['method'] === AGENT_COMMAND_DISPATCHED_METHOD
    )
}

export function isAgentGenerationEvent(event: Record<string, unknown>): boolean {
    if (event['type'] === 'pi_event') {
        const piEvent = event['event']
        return (
            typeof piEvent === 'object' &&
            piEvent !== null &&
            PI_GENERATION_EVENTS.has(String((piEvent as Record<string, unknown>)['type']))
        )
    }
    if (!isSessionUpdate(event)) {
        return false
    }
    const notification = event['notification'] as Record<string, unknown>
    const params = notification['params']
    if (typeof params !== 'object' || params === null) {
        return false
    }
    const update = (params as Record<string, unknown>)['update']
    return (
        typeof update === 'object' &&
        update !== null &&
        ACP_GENERATION_UPDATES.has(String((update as Record<string, unknown>)['sessionUpdate']))
    )
}

// fireCallback issues a best-effort POST to the Django agent-proxy callback.
// The call is fire-and-forget: the promise is not returned to the caller.
// Any failure is logged but never thrown into the ingest path.
//
// The original sandbox_event_ingest JWT is forwarded as the Authorization
// header so Django can re-validate it with validate_sandbox_event_ingest_token
// (same RS256 public key, same audience).
function fireCallback(
    runId: string,
    kind: SideEffectKind,
    agentActive: boolean,
    taskId: string,
    teamId: number,
    originalToken: string,
    config: Config,
    releaseClaim?: () => Promise<void>
): void {
    if (!config.djangoCallbackBaseUrl) {
        // Dev environment without AGENT_PROXY_DJANGO_CALLBACK_URL — skip silently.
        void releaseMilestoneClaim(releaseClaim, runId, kind)
        return
    }

    const url = `${config.djangoCallbackBaseUrl}/internal/tasks/runs/${runId}/agent-proxy-callback/`
    const body = JSON.stringify({ kind, agent_active: agentActive, task_id: taskId, team_id: teamId })

    const headers: Record<string, string> = {
        'Content-Type': 'application/json',
        Authorization: `Bearer ${originalToken}`,
    }
    // Service-to-service secret proving this call came from the proxy, not directly from a sandbox
    // (which also holds the ingest JWT). Django enforces it only when it has the same secret configured.
    if (config.agentProxyCallbackSecret) {
        headers['X-Agent-Proxy-Secret'] = config.agentProxyCallbackSecret
    }

    logger.debug('side_effect:fire', { run: runId, kind, agentActive })

    // Detached promise — errors are swallowed and logged.
    fetch(url, {
        method: 'POST',
        headers,
        body,
        // Node 18+ fetch doesn't expose a timeout option in the standard API;
        // we rely on the OS TCP timeout (typically 2 min). The callback is
        // best-effort so a slow/hanging response is acceptable.
    })
        .then(async (response) => {
            if (!response.ok) {
                logger.warn('side_effect:non_2xx', { run: runId, kind, status: response.status })
                await releaseMilestoneClaim(releaseClaim, runId, kind)
                return
            }
            const payload: unknown = await response.json().catch(() => null)
            const dispatched =
                typeof payload === 'object' &&
                payload !== null &&
                'dispatched' in payload &&
                payload.dispatched === true
            if (!dispatched) {
                await releaseMilestoneClaim(releaseClaim, runId, kind)
            }
        })
        .catch(async (err: unknown) => {
            const message = err instanceof Error ? err.message : String(err)
            logger.error('side_effect:failed', { run: runId, kind, error: message })
            await releaseMilestoneClaim(releaseClaim, runId, kind)
        })
}

async function releaseMilestoneClaim(
    release: (() => Promise<void>) | undefined,
    runId: string,
    kind: SideEffectKind
): Promise<void> {
    if (!release) {
        return
    }
    try {
        await release()
    } catch (err: unknown) {
        const message = err instanceof Error ? err.message : String(err)
        logger.error('side_effect:claim_release_failed', { run: runId, kind, error: message })
    }
}

// heartbeatWorkflowIfNeeded implements the side-effect decision from docs/DESIGN.md §2
// and mirrors event_ingest.py:_heartbeat_workflow_if_needed exactly.
//
// Decision tree:
//  1. isTurnComplete  -> setAgentActive(false), fire awaiting_input callback, return.
//  2. isSessionUpdate -> setAgentActive(true), set agentActive=true.
//  3. else            -> agentActive = getAgentActive().
//  4. if !agentActive -> return.
//  5. claimAgentActiveHeartbeat(30s) -> if throttled, return.
//  6. fire heartbeat callback.
//
// Redis operations are awaited synchronously (they gate the callback decision).
// The Django HTTP callback is fire-and-forget in both branches.
export async function heartbeatWorkflowIfNeeded(
    redisStream: TaskRunRedisStream,
    runId: string,
    event: Record<string, unknown>,
    taskId: string,
    teamId: number,
    originalToken: string,
    config: Config
): Promise<void> {
    if (isAgentCommandDispatched(event) && (await redisStream.claimFirstAgentCommand())) {
        fireCallback(runId, 'command_dispatched', false, taskId, teamId, originalToken, config, () =>
            redisStream.releaseFirstAgentCommand()
        )
    } else if (isAgentGenerationEvent(event) && (await redisStream.claimFirstAgentActivity())) {
        fireCallback(runId, 'agent_activity', true, taskId, teamId, originalToken, config, () =>
            redisStream.releaseFirstAgentActivity()
        )
    }

    if (isTurnComplete(event)) {
        await redisStream.setAgentActive(false)
        // Let Django decide whether the run is interactive; it will only
        // dispatch the push notification for interactive mode runs.
        fireCallback(runId, 'awaiting_input', false, taskId, teamId, originalToken, config)
        return
    }

    let agentActive: boolean
    if (isSessionUpdate(event)) {
        await redisStream.setAgentActive(true)
        agentActive = true
    } else {
        agentActive = await redisStream.getAgentActive()
    }

    if (!agentActive) {
        return
    }

    const claimed = await redisStream.claimAgentActiveHeartbeat(HEARTBEAT_THROTTLE_SECONDS)
    if (!claimed) {
        return
    }

    fireCallback(runId, 'heartbeat', true, taskId, teamId, originalToken, config)
}
