import { LemonButton, Spinner } from '@posthog/lemon-ui'

import { Query } from '~/queries/Query/Query'
import type { AnyResponseType, InsightVizNode } from '~/queries/schema/schema-general'

import { ChartDisplayIcon } from './ChartDisplayIcon'
import type { ChartDisplayOption } from './chartDisplayOptions'
import { ChartDisplaySketch } from './ChartDisplaySketch'

export function ChartPreviewTile({
    disabledReason,
    loading,
    onSelect,
    option,
    query,
    response,
    uniqueKey,
}: {
    disabledReason?: string
    loading: boolean
    onSelect: () => void
    option: ChartDisplayOption
    query: InsightVizNode
    response: AnyResponseType | null
    uniqueKey: string
}): JSX.Element {
    let body: JSX.Element
    if (response) {
        body = <Query uniqueKey={uniqueKey} query={query} cachedResults={response} readOnly embedded />
    } else if (loading) {
        body = (
            <div className="flex flex-1 items-center justify-center">
                <Spinner />
            </div>
        )
    } else {
        body = (
            <div className="flex flex-1 items-center justify-center">
                <span className="w-28 opacity-60">
                    <ChartDisplaySketch display={option.display} />
                </span>
            </div>
        )
    }

    return (
        <LemonButton
            type="secondary"
            className="h-auto min-h-0 w-72 shrink-0 snap-start items-stretch whitespace-normal p-0 text-left"
            data-attr={`chart-preview-${option.display}`}
            disabledReason={disabledReason}
            onClick={onSelect}
        >
            <span className="flex w-full flex-col">
                <span className="flex items-center gap-1 border-b px-2 py-1 text-sm font-medium">
                    <ChartDisplayIcon icon={option.icon} />
                    <span className="truncate">{option.label}</span>
                </span>
                <span className="pointer-events-none relative flex h-48 flex-col overflow-hidden" aria-hidden>
                    {body}
                </span>
            </span>
        </LemonButton>
    )
}
