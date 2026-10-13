import { useActions, useValues } from 'kea'

import { IconPencil } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { experimentLogic } from 'scenes/experiments/experimentLogic'
import { modalsLogic } from 'scenes/experiments/modalsLogic'

import { ExperimentConclusionComment } from './ExperimentConclusionComment'

// Mirrors the Hypothesis card in the Metrics tab so the two read as one family.
export function ExperimentConclusionCard(): JSX.Element | null {
    const { experiment } = useValues(experimentLogic)
    const { openEditConclusionModal } = useActions(modalsLogic)

    if (!experiment.conclusion) {
        return null
    }

    return (
        <div
            className="border border-primary rounded bg-[var(--color-bg-table)] px-3 py-2.5"
            data-attr="experiment-conclusion-card"
        >
            <div className="flex items-center gap-1">
                <span className="metric-cell-header font-bold">Conclusion</span>
                <LemonButton
                    type="tertiary"
                    size="xsmall"
                    icon={<IconPencil className="text-secondary" />}
                    tooltip="Edit conclusion"
                    onClick={openEditConclusionModal}
                    data-attr="experiment-edit-conclusion"
                />
            </div>
            {experiment.conclusion_comment ? (
                <ExperimentConclusionComment comment={experiment.conclusion_comment} />
            ) : (
                <p className="metric-cell font-normal m-0 mt-1 leading-relaxed italic">
                    Add a note about why this experiment ended
                </p>
            )}
        </div>
    )
}
