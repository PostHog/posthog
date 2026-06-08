/**
 * `/agents/[slug]/approvals` — per-agent approval inbox.
 */

import { ApprovalsSegment } from './approvals-client'

export default function AgentApprovalsPage(): React.ReactElement {
    return <ApprovalsSegment />
}
