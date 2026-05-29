/**
 * Per-area concierge declaration for the `/agents` surface. The dock
 * (in `AppShell`) reads this and chats with the named agent. Falls
 * back to a fixture runner until the concierge agent is deployed.
 */

'use client'

import { useSetDockConciergeAgent } from '@/components/dock-context'

export default function AgentsLayout({ children }: { children: React.ReactNode }): React.ReactElement {
    useSetDockConciergeAgent({ slug: 'agent-concierge' })
    return <>{children}</>
}
