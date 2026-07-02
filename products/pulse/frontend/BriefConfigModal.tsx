import { useActions, useValues } from 'kea'
import { Form } from 'kea-forms'

import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { LemonInput } from 'lib/lemon-ui/LemonInput'
import { LemonInputSelect } from 'lib/lemon-ui/LemonInputSelect'
import { LemonModal } from 'lib/lemon-ui/LemonModal'
import { LemonTextArea } from 'lib/lemon-ui/LemonTextArea'

import { dashboardsModel } from '~/models/dashboardsModel'

import { pulseLogic } from './pulseLogic'

export function BriefConfigModal(): JSX.Element {
    const { configModalOpen, editingConfig, isConfigFormSubmitting } = useValues(pulseLogic)
    const { closeConfigModal, submitConfigForm } = useActions(pulseLogic)
    const { nameSortedDashboards } = useValues(dashboardsModel)

    return (
        <LemonModal
            isOpen={configModalOpen}
            onClose={closeConfigModal}
            title={editingConfig ? `Edit "${editingConfig.name}"` : 'New brief config'}
            footer={
                <>
                    <LemonButton
                        onClick={closeConfigModal}
                        disabledReason={isConfigFormSubmitting ? 'Saving…' : undefined}
                    >
                        Cancel
                    </LemonButton>
                    <LemonButton type="primary" loading={isConfigFormSubmitting} onClick={submitConfigForm}>
                        {editingConfig ? 'Save' : 'Create'}
                    </LemonButton>
                </>
            }
        >
            <Form logic={pulseLogic} formKey="configForm" enableFormOnSubmit className="flex flex-col gap-2">
                <LemonField name="name" label="Name">
                    <LemonInput placeholder="e.g. Feature flags team" />
                </LemonField>
                <LemonField
                    name="focus_prompt"
                    label="Focus prompt"
                    info="Free text steering what the brief pays attention to and its tone."
                >
                    <LemonTextArea placeholder='e.g. "we’re the feature flags team — flag adoption, evaluation latency, SDK errors"' />
                </LemonField>
                <LemonField
                    name="dashboards"
                    label="Anchor dashboards"
                    info="The brief scouts the insights on these dashboards. Leave empty to fall back to the team's most recently accessed dashboards."
                >
                    {({ value, onChange }) => (
                        <LemonInputSelect
                            mode="multiple"
                            value={((value as number[]) ?? []).map(String)}
                            onChange={(ids) => onChange(ids.map(Number))}
                            options={nameSortedDashboards.map((dashboard) => ({
                                key: String(dashboard.id),
                                label: dashboard.name || 'Untitled',
                            }))}
                            placeholder="Select dashboards"
                        />
                    )}
                </LemonField>
            </Form>
        </LemonModal>
    )
}
