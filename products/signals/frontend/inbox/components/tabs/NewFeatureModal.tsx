import { useActions, useValues } from 'kea'

import { LemonButton, LemonModal, LemonTextArea } from '@posthog/lemon-ui'

import { featureCreateLogic } from '../../logics/featureCreateLogic'

export function NewFeatureModal(): JSX.Element {
    const { newFeatureModalOpen, descriptionDraft, creating } = useValues(featureCreateLogic)
    const { closeNewFeatureModal, setDescriptionDraft, createFeature } = useActions(featureCreateLogic)

    return (
        <LemonModal
            isOpen={newFeatureModalOpen}
            onClose={closeNewFeatureModal}
            title="New feature"
            description="Describe the feature you want to build. An agent will help you plan how to build and measure it."
            footer={
                <>
                    <LemonButton
                        type="secondary"
                        onClick={closeNewFeatureModal}
                        disabledReason={creating ? 'Creating…' : undefined}
                    >
                        Cancel
                    </LemonButton>
                    <LemonButton
                        type="primary"
                        onClick={createFeature}
                        loading={creating}
                        disabledReason={!descriptionDraft.trim() ? 'Describe the idea first' : undefined}
                    >
                        Start planning
                    </LemonButton>
                </>
            }
        >
            <LemonTextArea
                value={descriptionDraft}
                onChange={setDescriptionDraft}
                minRows={3}
                placeholder="e.g. A burndown chart widget for dashboards, driven by error tracking issues"
                autoFocus
            />
        </LemonModal>
    )
}
