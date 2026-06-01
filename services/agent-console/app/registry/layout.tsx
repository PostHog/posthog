/**
 * Per-area concierge declaration for the `/registry` surface. The dock
 * (in `AppShell`) reads this and chats with the same `agent-concierge`
 * agent — authoring tools / skills is what the concierge is for.
 *
 * Falls back to the fixture runner until the concierge agent is
 * actually deployed (see `<ConciergeDock>` in `Dock.tsx`).
 */

'use client'

import { useSetDockConciergeAgent } from '@/components/dock-context'

export default function RegistryLayout({ children }: { children: React.ReactNode }): React.ReactElement {
    useSetDockConciergeAgent({ slug: 'agent-concierge' })
    return <>{children}</>
}
