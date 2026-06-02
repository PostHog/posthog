'use client'

import { useState } from 'react'

import { useAgent } from '@/components/agent-context'
import { MemoryClassic } from '@/components/MemoryClassic'
import { MemoryTables } from '@/components/MemoryTables'

type Pane = 'files' | 'tables'

export function MemorySegment(): React.ReactElement {
    const agent = useAgent()
    const [pane, setPane] = useState<Pane>('files')
    return (
        <div className="flex h-full flex-col px-6 pb-6 pt-4">
            <div className="mb-3 flex w-fit overflow-hidden rounded border border-border text-xs">
                {(['files', 'tables'] as const).map((p) => (
                    <button
                        key={p}
                        type="button"
                        onClick={() => setPane(p)}
                        aria-pressed={pane === p}
                        className={`px-3 py-1 capitalize ${pane === p ? 'bg-muted font-medium' : 'hover:bg-accent'}`}
                    >
                        {p}
                    </button>
                ))}
            </div>
            <div className="min-h-0 flex-1">
                {pane === 'files' ? <MemoryClassic slug={agent.slug} /> : <MemoryTables slug={agent.slug} />}
            </div>
        </div>
    )
}
