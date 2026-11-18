import { LemonInput, LemonModal } from '@posthog/lemon-ui'

import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { ExperimentFlagKeyInput } from 'scenes/experiments/ExperimentFlagKeyInput'

import { Experiment } from '~/types'

import { DUPLICATE_EXPERIMENT_TITLE, copyNamePlaceholder, useDuplicateExperimentModal } from './experimentCopyModals'
import { QuillDuplicateExperimentModal } from './QuillExperimentCopyModals'

interface DuplicateExperimentModalProps {
    isOpen: boolean
    onClose: () => void
    experiment: Experiment
}

export function DuplicateExperimentModal(props: DuplicateExperimentModalProps): JSX.Element {
    const resultsRedesign = useFeatureFlag('EXPERIMENTS_RESULTS_REDESIGN')
    const todayRailNav = useFeatureFlag('TODAY_RAIL_NAV')
    if (todayRailNav && resultsRedesign) {
        return <QuillDuplicateExperimentModal {...props} />
    }
    return <LemonDuplicateExperimentModal {...props} />
}

function LemonDuplicateExperimentModal({ isOpen, onClose, experiment }: DuplicateExperimentModalProps): JSX.Element {
    const { experimentName, handleNameChange, handleDuplicate, handleClose, flagKeyInputProps } =
        useDuplicateExperimentModal(experiment, onClose)

    return (
        <LemonModal
            isOpen={isOpen}
            onClose={handleClose}
            title={DUPLICATE_EXPERIMENT_TITLE}
            width="max-content"
            footer={
                <div className="flex justify-end">
                    <LemonButton type="primary" onClick={handleDuplicate} data-attr="duplicate-experiment-submit">
                        Duplicate
                    </LemonButton>
                </div>
            }
        >
            <div className="space-y-4">
                <div className="text-muted max-w-xl">
                    Create a new experiment using the configuration from <strong>{experiment.name}</strong>.
                </div>

                <div>
                    <label className="font-semibold mb-1 block">Experiment name</label>
                    <LemonInput
                        value={experimentName}
                        onChange={handleNameChange}
                        placeholder={copyNamePlaceholder(experiment)}
                        autoFocus
                        data-attr="duplicate-experiment-name"
                    />
                </div>

                <ExperimentFlagKeyInput {...flagKeyInputProps} />
            </div>
        </LemonModal>
    )
}
