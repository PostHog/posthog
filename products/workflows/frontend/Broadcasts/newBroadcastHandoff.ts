import type { AiFirstHandoffLogicProps } from 'scenes/max/aiFirstCreate/aiFirstHandoffLogic'
import { urls } from 'scenes/urls'

import { findCreatedWorkflowId } from '../Workflows/newWorkflowHandoff'

// pinned: MCP tool name from products/workflows/mcp/tools.yaml
const CREATE_BROADCAST_TOOL = 'broadcasts-create'

/** A completed `broadcasts-create` opens the panel and routes to the draft in the broadcast wizard. */
export const NEW_BROADCAST_HANDOFF: AiFirstHandoffLogicProps = {
    toolName: CREATE_BROADCAST_TOOL,
    // A broadcast is a workflow row, so the workflow name lookup finds it too.
    findCreatedId: (innerInput) => findCreatedWorkflowId(innerInput?.name),
    urlFor: (id) => urls.broadcast(id),
    notOpenedMessage: 'Your broadcast was created, but it could not be opened. Find it in the broadcasts list.',
    // pinned: analytics event names
    eventPrefix: 'broadcast ai composer',
    createdEvent: 'broadcast ai composer created broadcast',
    createdIdProperty: 'broadcast_id',
}
