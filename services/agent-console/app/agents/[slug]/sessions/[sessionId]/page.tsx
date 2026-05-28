/**
 * `/agents/<slug>/sessions/<sessionId>` — single-session detail.
 * Playback (left) + log entries (right), correlated by call_id.
 */

import { notFound } from 'next/navigation'

import { getAgentBySlug, getSession, listLogsForSession } from '@/lib/mockApi'

import { SessionDetailClient } from './session-detail-client'

export default async function SessionDetailPage({
    params,
}: {
    params: Promise<{ slug: string; sessionId: string }>
}): Promise<React.ReactElement> {
    const { slug, sessionId } = await params
    const [agent, session, logs] = await Promise.all([
        getAgentBySlug(slug),
        getSession(sessionId),
        listLogsForSession(sessionId),
    ])
    if (!agent || !session) {
        notFound()
    }
    return <SessionDetailClient agent={agent} session={session} logs={logs} />
}
