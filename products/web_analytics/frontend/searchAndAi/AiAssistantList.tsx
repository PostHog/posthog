import { LemonButton, LemonSkeleton } from '@posthog/lemon-ui'

import { LemonProgress } from 'lib/lemon-ui/LemonProgress'
import { percentage } from 'lib/utils/numbers'
import { pluralize } from 'lib/utils/strings'

import { AiBrandLogo } from './AiBrandLogo'

export interface AiAssistantRow {
    assistant: string
    visitors: number
    views: number
}

export interface AiAssistantListProps {
    rows: AiAssistantRow[] | null
    loading: boolean
    emptyText: string
    failed?: boolean
    onRetry?: () => void
}

export function AiAssistantList({ rows, loading, emptyText, failed, onRetry }: AiAssistantListProps): JSX.Element {
    if (failed && !loading) {
        return (
            <div className="flex flex-col items-center gap-2 p-6 text-center">
                <p className="m-0 text-secondary">Couldn't load visitors by assistant.</p>
                {onRetry && (
                    <LemonButton type="secondary" size="small" onClick={onRetry}>
                        Try again
                    </LemonButton>
                )}
            </div>
        )
    }
    if (loading && !rows) {
        return (
            <div className="flex flex-col gap-3 p-4">
                {[0, 1, 2].map((index) => (
                    <LemonSkeleton key={index} className="h-6 w-full" />
                ))}
            </div>
        )
    }
    if (!rows || rows.length === 0) {
        return <p className="m-0 p-6 text-center text-secondary">{emptyText}</p>
    }
    const max = Math.max(...rows.map((row) => row.visitors), 1)
    const total = rows.reduce((sum, row) => sum + row.visitors, 0)
    return (
        <ol className="@container/assistant-list m-0 p-0 list-none flex flex-col" data-attr="ai-assistant-list">
            {rows.map((row) => {
                const share = total > 0 ? row.visitors / total : 0
                return (
                    <li
                        key={row.assistant}
                        className="grid grid-cols-[minmax(0,1fr)_auto] items-center gap-x-3 gap-y-1.5 px-4 py-2.5 border-t first:border-t-0 @min-[30rem]/assistant-list:grid-cols-[minmax(0,10rem)_minmax(0,1fr)_7rem]"
                    >
                        <span className="flex items-center gap-2 min-w-0">
                            <AiBrandLogo name={row.assistant} />
                            <span className="font-medium truncate">{row.assistant}</span>
                        </span>
                        <span className="col-span-2 order-last @min-[30rem]/assistant-list:col-span-1 @min-[30rem]/assistant-list:order-none">
                            <LemonProgress percent={(row.visitors / max) * 100} strokeColor="var(--data-color-3)" />
                        </span>
                        <span className="flex flex-col items-end leading-tight tabular-nums" translate="no">
                            <span className="font-semibold">{row.visitors.toLocaleString()}</span>
                            <span className="text-xs text-secondary">
                                {percentage(share, 0)} · {pluralize(row.views, 'view')}
                            </span>
                        </span>
                    </li>
                )
            })}
        </ol>
    )
}
