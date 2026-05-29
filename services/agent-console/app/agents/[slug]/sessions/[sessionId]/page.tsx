/**
 * `/agents/<slug>/sessions/<sessionId>` — single-session detail.
 * Shell only; the client wrapper fetches its own data.
 */

import { SessionDetailClient } from './session-detail-client'

export default async function SessionDetailPage({
    params,
}: {
    params: Promise<{ slug: string; sessionId: string }>
}): Promise<React.ReactElement> {
    const { slug, sessionId } = await params
    return <SessionDetailClient slug={slug} sessionId={sessionId} />
}
