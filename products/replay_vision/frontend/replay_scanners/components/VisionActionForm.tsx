import { useActions, useValues } from 'kea'
import { Form } from 'kea-forms'
import { useMemo } from 'react'

import { LemonButton, LemonInput, LemonModal, LemonSelect } from '@posthog/lemon-ui'

import { IntegrationChoice } from 'lib/components/CyclotronJob/integrations/IntegrationChoice'
import { integrationsLogic } from 'lib/integrations/integrationsLogic'
import { SlackChannelPicker, SlackNotConfiguredBanner } from 'lib/integrations/SlackIntegrationHelpers'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { LemonSearchableSelect } from 'lib/lemon-ui/LemonSelect/LemonSearchableSelect'
import { LemonTextArea } from 'lib/lemon-ui/LemonTextArea/LemonTextArea'
import { timeZoneLabel } from 'lib/utils/timezones'
import { preflightLogic } from 'scenes/PreflightCheck/preflightLogic'

import { CadenceFrequency, humanizeCadence } from '../cadence'
import { visionActionsLogic } from '../visionActionsLogic'

const FREQUENCY_OPTIONS: { value: CadenceFrequency; label: string }[] = [
    { value: 'daily', label: 'Daily' },
    { value: 'weekly', label: 'Weekly' },
    { value: 'monthly', label: 'Monthly' },
]

// 0=Mon … 6=Sun, matching CadenceState.weekdays.
const WEEKDAY_PILLS = ['Mo', 'Tu', 'We', 'Th', 'Fr', 'Sa', 'Su']

function TimezoneSelect({ value, onChange }: { value: string; onChange: (tz: string) => void }): JSX.Element {
    const { preflight } = useValues(preflightLogic)
    const options = useMemo(
        () =>
            Object.entries(preflight?.available_timezones || {}).map(([tz, offset]) => ({
                value: tz,
                label: timeZoneLabel(tz, offset),
            })),
        [preflight?.available_timezones]
    )
    return (
        <LemonSearchableSelect
            value={value}
            options={options}
            onChange={(val) => val && onChange(val)}
            placeholder="Select a timezone"
            fullWidth
        />
    )
}

function ScheduleSection(): JSX.Element {
    const { visionActionForm } = useValues(visionActionsLogic)
    const { setVisionActionFormValue } = useActions(visionActionsLogic)
    const { cadence, timezone } = visionActionForm

    const timeValue = `${cadence.hour.toString().padStart(2, '0')}:${cadence.minute.toString().padStart(2, '0')}`

    const toggleWeekday = (day: number): void => {
        const weekdays = cadence.weekdays.includes(day)
            ? cadence.weekdays.filter((d) => d !== day)
            : [...cadence.weekdays, day]
        setVisionActionFormValue('cadence', { ...cadence, weekdays })
    }

    return (
        <div className="flex flex-col gap-2">
            <div className="flex gap-2 items-end">
                <div className="flex-1">
                    <label className="text-sm font-semibold">Frequency</label>
                    <LemonSelect
                        value={cadence.frequency}
                        options={FREQUENCY_OPTIONS}
                        onChange={(frequency) =>
                            frequency && setVisionActionFormValue('cadence', { ...cadence, frequency })
                        }
                        fullWidth
                    />
                </div>
                <div className="w-32">
                    <label className="text-sm font-semibold">At</label>
                    <LemonInput
                        type="time"
                        value={timeValue}
                        onChange={(val) => {
                            const [h, m] = (val || '09:00').split(':').map((n) => parseInt(n, 10))
                            setVisionActionFormValue('cadence', {
                                ...cadence,
                                hour: Number.isNaN(h) ? 9 : h,
                                minute: Number.isNaN(m) ? 0 : m,
                            })
                        }}
                    />
                </div>
            </div>

            {cadence.frequency === 'weekly' && (
                <div>
                    <label className="text-sm font-semibold">On days</label>
                    <div className="flex gap-1">
                        {WEEKDAY_PILLS.map((label, day) => (
                            <LemonButton
                                key={day}
                                size="small"
                                type={cadence.weekdays.includes(day) ? 'primary' : 'secondary'}
                                onClick={() => toggleWeekday(day)}
                            >
                                {label}
                            </LemonButton>
                        ))}
                    </div>
                </div>
            )}

            <div>
                <label className="text-sm font-semibold">Timezone</label>
                <TimezoneSelect value={timezone} onChange={(tz) => setVisionActionFormValue('timezone', tz)} />
            </div>

            <span className="text-xs text-muted">{humanizeCadence(cadence)}</span>
        </div>
    )
}

function DeliverySection(): JSX.Element {
    const { visionActionForm } = useValues(visionActionsLogic)
    const { setVisionActionFormValue } = useActions(visionActionsLogic)
    const { slackIntegrations } = useValues(integrationsLogic)
    const { integration_id } = visionActionForm

    if (!slackIntegrations?.length) {
        return <SlackNotConfiguredBanner />
    }

    const selectedIntegration = slackIntegrations.find((i) => i.id === integration_id)

    return (
        <div className="flex flex-col gap-2">
            <IntegrationChoice
                integration="slack"
                value={integration_id ?? undefined}
                onChange={(value) => {
                    setVisionActionFormValue('integration_id', value)
                    setVisionActionFormValue('channel', '')
                }}
            />
            {selectedIntegration && (
                <LemonField name="channel" label="Channel">
                    {({ value, onChange }) => (
                        <SlackChannelPicker
                            integration={selectedIntegration}
                            value={value}
                            onChange={(next) => onChange(next ?? '')}
                        />
                    )}
                </LemonField>
            )}
        </div>
    )
}

export function VisionActionForm({ scannerId }: { scannerId: string }): JSX.Element {
    const { formVisible, editingAction, isVisionActionFormSubmitting } = useValues(visionActionsLogic)
    const { closeForm } = useActions(visionActionsLogic)

    return (
        <LemonModal
            isOpen={formVisible}
            onClose={closeForm}
            width={640}
            title={editingAction ? 'Edit action' : 'New action'}
            description="Schedule an AI summary of this scanner's observations and deliver it to Slack."
            footer={
                <div className="flex gap-2 justify-end">
                    <LemonButton type="secondary" onClick={closeForm}>
                        Cancel
                    </LemonButton>
                    <LemonButton
                        type="primary"
                        htmlType="submit"
                        form="vision-action-form"
                        loading={isVisionActionFormSubmitting}
                    >
                        {editingAction ? 'Save' : 'Create action'}
                    </LemonButton>
                </div>
            }
        >
            <Form
                logic={visionActionsLogic}
                props={{ scannerId }}
                formKey="visionActionForm"
                id="vision-action-form"
                enableFormOnSubmit
                className="flex flex-col gap-4"
            >
                <LemonField name="name" label="Name">
                    <LemonInput placeholder="Daily checkout summary" autoFocus />
                </LemonField>

                <div>
                    <h4 className="mb-1">Schedule</h4>
                    <ScheduleSection />
                </div>

                <LemonField name="prompt_guide" label="Guidance" info="Optional. Steers how the AI writes the summary.">
                    <LemonTextArea
                        placeholder="e.g. focus on checkout drop-off and highlight any errors"
                        maxLength={500}
                    />
                </LemonField>

                <div>
                    <h4 className="mb-1">Deliver to Slack</h4>
                    <DeliverySection />
                </div>
            </Form>
        </LemonModal>
    )
}
