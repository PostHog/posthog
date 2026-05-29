/**
 * `/agents/<slug>/memory` — file explorer + reader for the agent's S3-backed
 * memory. Shell only; the client wrapper fetches data via `apiClient`.
 */

import { MemoryClient } from './memory-client'

export default async function AgentMemoryPage({
    params,
}: {
    params: Promise<{ slug: string }>
}): Promise<React.ReactElement> {
    const { slug } = await params
    return <MemoryClient slug={slug} />
}
