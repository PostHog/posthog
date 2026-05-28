'use client'

import { useRouter } from 'next/navigation'

import type { ChatSession } from '@posthog/agent-chat'
import type { AgentApplicationFixture, LogEntry } from '@posthog/agent-chat/fixtures'

import { useSetDockPage } from '@/components/dock-context'
import { SessionDetail } from '@/pages/SessionDetail'

export function SessionDetailClient({
    agent,
    session,
    logs,
}: {
    agent: AgentApplicationFixture
    session: ChatSession
    logs: LogEntry[]
}): React.ReactElement {
    const agentRef = { id: agent.id, slug: agent.slug, name: agent.name }
    useSetDockPage({ kind: 'agent-session', agent: agentRef, sessionId: session.id })

    const router = useRouter()

    return (
        <SessionDetail
            agent={agent}
            session={session}
            logs={logs}
            onBackToList={() => router.push('/')}
            onBackToAgent={() => router.push(`/agents/${agent.slug}`)}
        />
    )
}
