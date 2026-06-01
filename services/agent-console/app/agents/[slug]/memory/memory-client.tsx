'use client'

import { useAgent } from '@/components/agent-context'
import { MemoryClassic } from '@/components/MemoryClassic'

export function MemorySegment(): React.ReactElement {
    const agent = useAgent()
    return (
        <div className="h-full px-6 pb-6 pt-4">
            <MemoryClassic slug={agent.slug} />
        </div>
    )
}
