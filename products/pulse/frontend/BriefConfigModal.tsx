import { useActions, useValues } from 'kea'
import { Form } from 'kea-forms'

import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonDialog } from 'lib/lemon-ui/LemonDialog'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { LemonInput } from 'lib/lemon-ui/LemonInput'
import { LemonInputSelect } from 'lib/lemon-ui/LemonInputSelect'
import { LemonLabel } from 'lib/lemon-ui/LemonLabel/LemonLabel'
import { LemonModal } from 'lib/lemon-ui/LemonModal'
import { LemonSelect } from 'lib/lemon-ui/LemonSelect'
import { LemonTextArea } from 'lib/lemon-ui/LemonTextArea'

import { dashboardsModel } from '~/models/dashboardsModel'

import { pulseLogic } from './pulseLogic'

function SchedulingSection(): JSX.Element {
    const {
        editingConfigSubscription,
        briefSubscriptionsLoading,
        isScheduleFormSubmitting,
        subscriptionIdBeingUnscheduled,
    } = useValues(pulseLogic)
    const { unscheduleBrief } = useActions(pulseLogic)

    if (editingConfigSubscription) {
        const isUnscheduling = subscriptionIdBeingUnscheduled === editingConfigSubscription.id
        return (
            <div className="flex items-center justify-between gap-2">
                <div>
                    <div>
                        Delivered to <strong>{editingConfigSubscription.target_value.split(',').join(', ')}</strong>
                    </div>
                    <div className="text-muted">{editingConfigSubscription.summary}</div>
                </div>
                <LemonButton
                    type="secondary"
                    status="danger"
                    size="small"
                    loading={isUnscheduling}
                    disabledReason={isUnscheduling ? 'Removing…' : undefined}
                    onClick={() =>
                        LemonDialog.open({
                            title: 'Remove this schedule?',
                            description: 'The brief will no longer be generated and delivered on a schedule.',
                            primaryButton: {
                                children: 'Remove',
                                status: 'danger',
                                onClick: () => unscheduleBrief(editingConfigSubscription.id),
                            },
                            secondaryButton: { children: 'Cancel' },
                        })
                    }
                >
                    Remove schedule
                </LemonButton>
            </div>
        )
    }

    return (
        <Form logic={pulseLogic} formKey="scheduleForm" enableFormOnSubmit className="flex flex-col gap-2">
            <LemonField name="frequency" label="Frequency">
                <LemonSelect
                    options={[
                        { value: 'daily', label: 'Daily' },
                        { value: 'weekly', label: 'Weekly' },
                    ]}
                />
            </LemonField>
            <LemonField name="target_value" label="Send to">
                {({ value, onChange }) => (
                    <LemonInputSelect
                        mode="multiple"
                        allowCustomValues
                        value={((value as string) ?? '').split(',').filter(Boolean)}
                        onChange={(emails) => onChange(emails.join(','))}
                        placeholder="Enter email addresses"
                        data-attr="pulse-schedule-emails"
                    />
                )}
            </LemonField>
            <div>
                <LemonButton
                    type="primary"
                    size="small"
                    htmlType="submit"
                    loading={isScheduleFormSubmitting}
                    disabledReason={briefSubscriptionsLoading ? 'Loading existing schedule…' : undefined}
                >
                    Schedule this brief
                </LemonButton>
            </div>
        </Form>
    )
}

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
                    name="goal"
                    label="Goal"
                    info="What should this focus be driving toward? Briefs open with progress toward it and rank opportunities by goal impact."
                >
                    <LemonTextArea placeholder='e.g. "increase subscription usage"' />
                </LemonField>
                <LemonField
                    name="goal_metric_short_id"
                    label="Goal metric insight"
                    info="Optional: the short ID of a trends insight measuring the goal. Briefs state its current vs previous per-day rate."
                >
                    <LemonInput placeholder="Insight short ID, e.g. AbC123xY" />
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
            {editingConfig ? (
                <div className="mt-4 flex flex-col gap-2 border-t pt-4">
                    <LemonLabel info="The brief is generated and delivered by email on this schedule. The config decides what the brief covers; the schedule decides when and where it goes.">
                        Scheduling
                    </LemonLabel>
                    <SchedulingSection />
                </div>
            ) : null}
        </LemonModal>
    )
}
