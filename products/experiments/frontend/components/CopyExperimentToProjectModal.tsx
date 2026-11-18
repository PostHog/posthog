import { LemonInput, LemonModal, LemonSelect } from '@posthog/lemon-ui'

import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { ExperimentFlagKeyInput } from 'scenes/experiments/ExperimentFlagKeyInput'

import { Experiment } from '~/types'

import {
    COPY_EXPERIMENT_DESCRIPTION,
    COPY_EXPERIMENT_TITLE,
    SELECT_PROJECT_REASON,
    copyNamePlaceholder,
    useCopyExperimentToProjectModal,
} from './experimentCopyModals'
import { QuillCopyExperimentToProjectModal } from './QuillExperimentCopyModals'

interface CopyExperimentToProjectModalProps {
    isOpen: boolean
    onClose: () => void
    experiment: Experiment
}

export function CopyExperimentToProjectModal(props: CopyExperimentToProjectModalProps): JSX.Element {
    const resultsRedesign = useFeatureFlag('EXPERIMENTS_RESULTS_REDESIGN')
    const todayRailNav = useFeatureFlag('TODAY_RAIL_NAV')
    if (todayRailNav && resultsRedesign) {
        return <QuillCopyExperimentToProjectModal {...props} />
    }
    return <LemonCopyExperimentToProjectModal {...props} />
}

function LemonCopyExperimentToProjectModal({
    isOpen,
    onClose,
    experiment,
}: CopyExperimentToProjectModalProps): JSX.Element {
    const {
        teamOptions,
        selectedTeamId,
        handleTeamChange,
        experimentName,
        handleNameChange,
        handleCopy,
        handleClose,
        copying,
        flagKeyInputProps,
    } = useCopyExperimentToProjectModal({ isOpen, onClose, experiment })

    return (
        <LemonModal
            isOpen={isOpen}
            onClose={handleClose}
            title={COPY_EXPERIMENT_TITLE}
            width="max-content"
            footer={
                <div className="flex justify-end">
                    <LemonButton
                        type="primary"
                        disabledReason={!selectedTeamId ? SELECT_PROJECT_REASON : undefined}
                        onClick={handleCopy}
                        loading={copying}
                    >
                        Copy
                    </LemonButton>
                </div>
            }
        >
            <div className="space-y-4">
                <div className="text-muted max-w-xl">{COPY_EXPERIMENT_DESCRIPTION}</div>

                <div>
                    <div className="font-semibold mb-2">Destination project</div>
                    <LemonSelect
                        placeholder={SELECT_PROJECT_REASON}
                        fullWidth
                        dropdownMatchSelectWidth={false}
                        value={selectedTeamId}
                        onChange={handleTeamChange}
                        options={teamOptions}
                    />
                </div>

                {selectedTeamId && (
                    <>
                        <div>
                            <label className="font-semibold mb-1 block">Experiment name</label>
                            <LemonInput
                                value={experimentName}
                                onChange={handleNameChange}
                                placeholder={copyNamePlaceholder(experiment)}
                                data-attr="copy-experiment-name"
                            />
                        </div>

                        <ExperimentFlagKeyInput {...flagKeyInputProps} />
                    </>
                )}
            </div>
        </LemonModal>
    )
}
