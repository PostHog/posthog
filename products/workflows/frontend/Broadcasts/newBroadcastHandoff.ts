import { ApiConfig } from 'lib/api'
import type { AiFirstHandoffLogicProps } from 'scenes/max/aiFirstCreate/aiFirstHandoffLogic'
import { urls } from 'scenes/urls'

import { hogFlowsList } from 'products/workflows/frontend/generated/api'

// pinned: MCP tool name from products/workflows/mcp/tools.yaml
const CREATE_BROADCAST_TOOL = 'broadcasts-create'

/**
 * Fallback for a completed create whose output carries no record: the draft is found by exact name among
 * broadcasts only, newest `created_at` first, so a workflow of the same name is never opened as one.
 */
export async function findCreatedBroadcastId(name: unknown): Promise<string | null> {
    const search = typeof name === 'string' && name.trim() ? name.trim() : undefined
    if (!search) {
        return null
    }
    const { results } = await hogFlowsList(String(ApiConfig.getCurrentTeamId()), {
        search,
        origin_product: 'broadcasts',
        limit: 5,
    })
    const match = results
        .filter((broadcast) => broadcast.name === search)
        .sort((a, b) => b.created_at.localeCompare(a.created_at))[0]
    return match?.id ?? null
}

/** A completed `broadcasts-create` opens the panel and routes to the draft in the broadcast wizard. */
export const NEW_BROADCAST_HANDOFF: AiFirstHandoffLogicProps = {
    toolName: CREATE_BROADCAST_TOOL,
    findCreatedId: (innerInput) => findCreatedBroadcastId(innerInput?.name),
    urlFor: (id) => urls.broadcast(id),
    notOpenedMessage: 'Your broadcast was created, but it could not be opened. Find it in the broadcasts list.',
    // pinned: analytics event names
    eventPrefix: 'broadcast ai composer',
    createdEvent: 'broadcast ai composer created broadcast',
    createdIdProperty: 'broadcast_id',
}
