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
    const {
        configModalOpen,
        editingConfig,
        isConfigFormSubmitting,
        goalMetricInsightOptions,
        goalMetricInsightsLoading,
    } = useValues(pulseLogic)
    const { closeConfigModal, submitConfigForm, setGoalMetricSearch } = useActions(pulseLogic)
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
                    <LemonTextArea placeholder="e.g. Increase adoption of our new onboarding flow and cut week-one drop-off" />
                </LemonField>
                <LemonField
                    name="goal"
                    label="Goal"
                    info="What should this focus be driving toward? Briefs open with progress toward it and rank opportunities by goal impact."
                >
                    <LemonTextArea placeholder='e.g. "increase subscription usage"' />
                </LemonField>
                <LemonField
                    name="goal_metric_short_id"
                    label="Goal metric insight"
                    info="Optional: a trends insight measuring the goal. Briefs state its current vs previous per-day rate."
                >
                    {({ value, onChange }) => (
                        <LemonInputSelect
                            mode="single"
                            singleValueAsSnack
                            placeholder="Search trends insights…"
                            value={value ? [value as string] : []}
                            options={goalMetricInsightOptions}
                            loading={goalMetricInsightsLoading}
                            onInputChange={setGoalMetricSearch}
                            onChange={(newValues) => onChange(newValues[0] ?? '')}
                        />
                    )}
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
