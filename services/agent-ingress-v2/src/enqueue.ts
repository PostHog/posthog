/**
 * One place to build + enqueue an AgentSession. Triggers call this with the
 * resolved (application, revision), the seed conversation message, and any
 * externalKey for dedupe.
 *
 * externalKey rule: if an existing session for (application, externalKey)
 * exists and is not in a terminal state, append the new message to it and
 * re-enqueue. Otherwise create a fresh session. This is what makes Slack
 * thread-anchored conversations work.
 */

import { randomUUID } from 'crypto'

import { AgentApplication, AgentRevision, ConversationMessage, SessionQueue } from '@posthog/agent-shared-v2'

export interface EnqueueDeps {
    queue: SessionQueue
    teamId: number
}

export interface EnqueueInput {
    application: AgentApplication
    revision: AgentRevision
    externalKey: string | null
    seed: ConversationMessage
}

export interface EnqueueResult {
    sessionId: string
    isResume: boolean
}

export async function enqueueOrResume(deps: EnqueueDeps, input: EnqueueInput): Promise<EnqueueResult> {
    if (input.externalKey) {
        const existing = await deps.queue.findByExternalKey(input.application.id, input.externalKey)
        if (existing && existing.state !== 'completed' && existing.state !== 'failed') {
            await deps.queue.appendMessage(existing.id, input.seed)
            await deps.queue.update(existing.id, { state: 'queued' })
            return { sessionId: existing.id, isResume: true }
        }
    }
    const session = {
        id: randomUUID(),
        application_id: input.application.id,
        revision_id: input.revision.id,
        team_id: deps.teamId,
        external_key: input.externalKey,
        state: 'queued' as const,
        conversation: [input.seed],
        created_at: new Date().toISOString(),
        updated_at: new Date().toISOString(),
    }
    await deps.queue.enqueue(session)
    return { sessionId: session.id, isResume: false }
}
