import { LemonButton, Spinner } from '@posthog/lemon-ui'

import { Query } from '~/queries/Query/Query'
import type { AnyResponseType, InsightVizNode } from '~/queries/schema/schema-general'

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
                <span className="w-24 opacity-60">
                    <ChartDisplaySketch display={option.display} />
                </span>
            </div>
        )
    }

    return (
        <LemonButton
            type="secondary"
            noPadding
            className="relative h-40 w-60 shrink-0 snap-start whitespace-normal text-left"
            data-attr={`chart-preview-${option.display}`}
            tooltip={option.label}
            aria-label={option.label}
            disabledReason={disabledReason}
            onClick={onSelect}
        >
            <span className="pointer-events-none absolute inset-0 flex flex-col overflow-hidden" aria-hidden>
                {body}
            </span>
        </LemonButton>
    )
}
