import { useActions, useValues } from 'kea'
import { useMemo } from 'react'

import { Skeleton } from '@posthog/quill-primitives'

import { mcpAnalyticsToolDetailLogic } from '../mcpAnalyticsToolDetailLogic'
import { ExampleCallRow } from './ExampleCallRow'
import type { ExampleCall, ExampleKind, ToolExamples as ToolExamplesData } from './toolReportQueries'

const KIND_ORDER: ExampleKind[] = ['errored', 'slow', 'succeeded']

interface FlaggedCall {
    call: ExampleCall
    kinds: ExampleKind[]
}

/** One list, newest first, each tagged with its kinds. */
export function mergeExamples(examples: ToolExamplesData): FlaggedCall[] {
    const byUuid = new Map<string, FlaggedCall>()
    for (const kind of KIND_ORDER) {
        for (const call of examples[kind]) {
            const entry = byUuid.get(call.uuid) ?? { call, kinds: [] }
            entry.kinds.push(kind)
            byUuid.set(call.uuid, entry)
        }
    }
    return [...byUuid.values()].sort((a, b) => b.call.timestamp.localeCompare(a.call.timestamp))
}

export function ToolExamples(): JSX.Element {
    const { examples, examplesLoading } = useValues(mcpAnalyticsToolDetailLogic)
    const { openExample } = useActions(mcpAnalyticsToolDetailLogic)
    const calls = useMemo(() => mergeExamples(examples), [examples])

    return (
        <div className="overflow-hidden rounded border border-primary bg-surface-primary">
            {examplesLoading && calls.length === 0 ? (
                <Skeleton className="h-40 rounded-none" aria-busy />
            ) : calls.length === 0 ? (
                <div className="p-4 text-sm text-secondary">No calls in this date range.</div>
            ) : (
                <div className="divide-y divide-primary">
                    {calls.map(({ call, kinds }) => (
                        <ExampleCallRow key={call.uuid} call={call} kinds={kinds} onOpen={openExample} />
                    ))}
                </div>
            )}
        </div>
    )
}
