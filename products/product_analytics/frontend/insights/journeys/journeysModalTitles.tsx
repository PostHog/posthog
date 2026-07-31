import { pluralize } from 'lib/utils/strings'

import { PathsV2Item } from '~/queries/schema/schema-general'

import { journeyItemLabel } from './journeyGridModel'

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

export function journeysChainModalTitle(chain: PathsV2Item[]): string {
    return `People who went ${chain.map(journeyItemLabel).join(' → ')}`
}

export function journeysEdgeModalTitle(
    stepIndex: number,
    sourceItem: PathsV2Item | null,
    targetItem: PathsV2Item | null,
    anyStepCount: number | null
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
                <div className="text-sm font-normal text-secondary">
                    {pluralize(anyStepCount, 'person', 'people')} went {sourceLabel} → {targetLabel} at any step
                </div>
            )}
        </>
    )
}
