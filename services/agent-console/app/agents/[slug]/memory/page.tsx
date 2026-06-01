/**
 * `/agents/[slug]/memory` — file explorer over the agent's
 * S3-backed memory store. No segment-local URL state today.
 */

import { MemorySegment } from './memory-client'

export default function MemoryPage(): React.ReactElement {
    return <MemorySegment />
}
