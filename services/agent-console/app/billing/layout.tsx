/**
 * Per-area concierge declaration for the `/billing` surface. The dock
 * (in `AppShell`) reads this and chats with the named agent. Falls
 * back to a fixture runner until the billing-bot agent is deployed.
 */

'use client'

import { useSetDockConciergeAgent } from '@/components/dock-context'

export default function BillingLayout({ children }: { children: React.ReactNode }): React.ReactElement {
    useSetDockConciergeAgent({ slug: 'billing-bot' })
    return <>{children}</>
}
