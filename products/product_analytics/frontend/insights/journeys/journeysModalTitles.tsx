import { pluralize } from 'lib/utils/strings'

import { PathsV2Item } from '~/queries/schema/schema-general'
import { InsightLogicProps } from '~/types'

import { journeyItemLabel } from './journeyGridModel'
import { JourneysViewAsFunnelButton } from './JourneysViewAsFunnelButton'

const OTHER_LABEL = 'less common items'

function stepNumber(stepIndex: number): number {
    return stepIndex + 1
}

export function journeysNodeModalTitle(stepIndex: number, item: PathsV2Item): string {
    return `People at ${journeyItemLabel(item)} (step ${stepNumber(stepIndex)})`
}

export function journeysOtherModalTitle(stepIndex: number): string {
    return `People at ${OTHER_LABEL} (step ${stepNumber(stepIndex)})`
}

export function journeysDropOffModalTitle(stepIndex: number): string {
    return `People whose journey ends at step ${stepNumber(stepIndex)}`
}

export function journeysChainModalTitle(chain: PathsV2Item[], logicProps?: InsightLogicProps): JSX.Element {
    return (
        <div className="flex items-center gap-2">
            <span>People who went {chain.map(journeyItemLabel).join(' → ')}</span>
            {logicProps && chain.length >= 2 && (
                <JourneysViewAsFunnelButton
                    logicProps={logicProps}
                    items={chain}
                    tooltip="Opens this path as a new funnel insight. Its step counts match the highlighted path."
                />
            )}
        </div>
    )
}

export function journeysEdgeModalTitle(
    stepIndex: number,
    sourceItem: PathsV2Item | null,
    targetItem: PathsV2Item | null,
    anyStepCount: number | null,
    logicProps?: InsightLogicProps
): JSX.Element {
    const sourceLabel = sourceItem ? journeyItemLabel(sourceItem) : OTHER_LABEL
    const targetLabel = targetItem ? journeyItemLabel(targetItem) : OTHER_LABEL
    return (
        <>
            <div>
                People who went {sourceLabel} → {targetLabel} (step {stepNumber(stepIndex)} →{' '}
                {stepNumber(stepIndex + 1)})
            </div>
            {anyStepCount !== null && sourceItem && targetItem && (
                <div className="flex items-center gap-2 text-sm font-normal text-secondary">
                    <span>
                        {pluralize(anyStepCount, 'person', 'people')} went {sourceLabel} → {targetLabel} at any step
                    </span>
                    {logicProps && (
                        <JourneysViewAsFunnelButton
                            logicProps={logicProps}
                            items={[sourceItem, targetItem]}
                            tooltip="Opens a new funnel insight counting this transition at any step. Its count matches the number shown here."
                        />
                    )}
                </div>
            )}
        </>
    )
}
