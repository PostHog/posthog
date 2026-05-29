/**
 * `/agents/<slug>` — agent overview. Shell only; the client wrapper
 * fetches its own data via the typed apiClient.
 */

import { AgentDetailClient } from './agent-detail-client'

export default async function AgentDetailPage({
    params,
}: {
    params: Promise<{ slug: string }>
}): Promise<React.ReactElement> {
    const { slug } = await params
    return <AgentDetailClient slug={slug} />
}
