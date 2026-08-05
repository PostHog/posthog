import { useActions, useValues } from 'kea'

import { LemonBanner, LemonButton, LemonModal } from '@posthog/lemon-ui'

import { experimentTemplateModalLogic } from './experimentTemplateModalLogic'

interface ExperimentTemplateModalProps {
    onApply: () => void
}

export const ExperimentTemplateModal = ({ onApply }: ExperimentTemplateModalProps): JSX.Element | null => {
    const { isModalOpen, template } = useValues(experimentTemplateModalLogic)
    const { closeTemplateModal } = useActions(experimentTemplateModalLogic)

    if (!isModalOpen || !template) {
        return null
    }

    const canApplyTemplate = true

    return (
        <LemonModal
            isOpen={isModalOpen}
            onClose={closeTemplateModal}
            title={`Configure: ${template.name}`}
            footer={
                <div className="flex items-center w-full justify-end gap-2">
                    <LemonButton type="secondary" onClick={closeTemplateModal}>
                        Cancel
                    </LemonButton>
                    <LemonButton
                        type="primary"
                        onClick={onApply}
                        disabledReason={!canApplyTemplate ? 'Please fill in all required event fields' : undefined}
                        data-attr="apply-experiment-template"
                    >
                        Apply Template
                    </LemonButton>
                </div>
            }
        >
            <div className="space-y-4">
                <LemonBanner type="info">
                    <strong>Goal:</strong> {template.experimentGoal}
                </LemonBanner>

                <div className="space-y-4">
                    {template.metrics.map((metric) => (
                        <div key={metric.name}>{metric.name}</div>
                    ))}
                </div>

                <LemonBanner type="success">
                    This will add {template.metrics.length} metrics:{' '}
                    {template.metrics.map((metric) => metric.name).join(', ')}
                </LemonBanner>
            </div>
        </LemonModal>
    )
}
