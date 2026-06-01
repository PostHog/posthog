/**
 * `/agents/[slug]/connections` — secrets, integrations, MCP servers.
 *
 * Owns its own URL state: `?edit_secret=<KEY>` opens the editor modal,
 * `?callback_session=<id>` carries the concierge callback target. The
 * params are scoped to this segment by construction — navigating to
 * any other tab drops them automatically.
 */

import { ConnectionsSegment } from './connections-client'

export default function ConnectionsPage(): React.ReactElement {
    return <ConnectionsSegment />
}
