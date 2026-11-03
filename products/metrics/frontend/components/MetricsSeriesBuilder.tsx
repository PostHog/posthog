import { useActions, useValues } from 'kea'

import { IconPlusSmall } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { MetricsClauseRow } from './MetricsClauseRow'
import { MetricsFormulaInput } from './MetricsFormulaInput'
import { MAX_CLAUSES, metricsViewerLogic } from './metricsViewerLogic'

export function MetricsSeriesBuilder({
    dataAttrPrefix,
    disabledReason,
}: {
    dataAttrPrefix: string
    disabledReason: string | null
}): JSX.Element {
    const { viewerClauses, activeClauseIndex, formula } = useValues(metricsViewerLogic)
    const { addClause } = useActions(metricsViewerLogic)

    const showFormulaInput = viewerClauses.length > 1 || formula !== ''

    return (
        <div
            className="flex flex-col flex-1 min-w-[16rem] border rounded bg-surface-primary divide-y"
            data-attr={`${dataAttrPrefix}-series`}
        >
            {viewerClauses.map((clause, index) => (
                <div key={clause.name} className="p-2">
                    <MetricsClauseRow
                        clause={clause}
                        index={index}
                        isActive={index === activeClauseIndex}
                        showAlias={viewerClauses.length > 1}
                        disabledReason={disabledReason}
                    />
                </div>
            ))}
            <div className="flex flex-wrap items-center gap-2 p-2 bg-surface-secondary rounded-b">
                <LemonButton
                    size="small"
                    type="tertiary"
                    icon={<IconPlusSmall />}
                    onClick={() => addClause()}
                    disabledReason={
                        disabledReason ??
                        (viewerClauses.length >= MAX_CLAUSES
                            ? `A query can have at most ${MAX_CLAUSES} series`
                            : undefined)
                    }
                    data-attr={`${dataAttrPrefix}-add-series`}
                >
                    Add series
                </LemonButton>
                {showFormulaInput && <MetricsFormulaInput disabledReason={disabledReason} />}
            </div>
        </div>
    )
}
