import { useActions, useValues } from 'kea'
import { Form } from 'kea-forms'
import { useMemo } from 'react'

import { LemonButton, LemonInput } from '@posthog/lemon-ui'

import { IntegrationChoice } from 'lib/components/CyclotronJob/integrations/IntegrationChoice'
import { integrationsLogic } from 'lib/integrations/integrationsLogic'
import { SlackChannelPicker, SlackNotConfiguredBanner } from 'lib/integrations/SlackIntegrationHelpers'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { LemonSearchableSelect } from 'lib/lemon-ui/LemonSelect/LemonSearchableSelect'
import { LemonTextArea } from 'lib/lemon-ui/LemonTextArea/LemonTextArea'
import { timeZoneLabel } from 'lib/utils/timezones'
import { preflightLogic } from 'scenes/PreflightCheck/preflightLogic'
import { SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'
import { ProductKey } from '~/queries/schema/schema-general'

import { ReplayVisionFeedbackButton } from '../components/ReplayVisionFeedbackButton'
import { actionEditorSceneLogic } from './actionEditorSceneLogic'
import { DEFAULT_CADENCE, humanizeCadence } from './cadence'

export const scene: SceneExport = {
    component: ActionEditorSceneComponent,
    logic: actionEditorSceneLogic,
    productKey: ProductKey.REPLAY_VISION,
}

// 0=Mon … 6=Sun, matching CadenceState.weekdays.
const WEEKDAY_PILLS = ['Mo', 'Tu', 'We', 'Th', 'Fr', 'Sa', 'Su']
const ALL_WEEKDAYS = [0, 1, 2, 3, 4, 5, 6]
const WEEKDAYS_MON_FRI = [0, 1, 2, 3, 4]

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
    const { actionForm } = useValues(actionEditorSceneLogic)
    const { setActionFormValue } = useActions(actionEditorSceneLogic)
    const { cadence, timezone } = actionForm

    const timeValue = `${cadence.hour.toString().padStart(2, '0')}:${cadence.minute.toString().padStart(2, '0')}`

    const setWeekdays = (weekdays: number[]): void => setActionFormValue('cadence', { ...cadence, weekdays })

    const toggleWeekday = (day: number): void =>
        setWeekdays(
            cadence.weekdays.includes(day) ? cadence.weekdays.filter((d) => d !== day) : [...cadence.weekdays, day]
        )

    const noDays = cadence.weekdays.length === 0

    return (
        <div className="flex flex-col gap-2">
            <div>
                <div className="flex items-center justify-between">
                    <label className="text-sm font-semibold">Runs on</label>
                    <div className="flex gap-1">
                        <LemonButton
                            size="xsmall"
                            type="tertiary"
                            onClick={() => setWeekdays([...ALL_WEEKDAYS])}
                            data-attr="vision-action-cadence-everyday"
                        >
                            Every day
                        </LemonButton>
                        <LemonButton
                            size="xsmall"
                            type="tertiary"
                            onClick={() => setWeekdays([...WEEKDAYS_MON_FRI])}
                            data-attr="vision-action-cadence-weekdays"
                        >
                            Weekdays
                        </LemonButton>
                    </div>
                </div>
                <div className="flex gap-1">
                    {WEEKDAY_PILLS.map((label, day) => (
                        <LemonButton
                            key={day}
                            size="small"
                            type={cadence.weekdays.includes(day) ? 'primary' : 'secondary'}
                            onClick={() => toggleWeekday(day)}
                            data-attr={`vision-action-cadence-day-${day}`}
                        >
                            {label}
                        </LemonButton>
                    ))}
                </div>
                {noDays && <span className="text-xs text-danger">Pick at least one day</span>}
            </div>

            <div className="w-32">
                <label className="text-sm font-semibold">At</label>
                <LemonInput
                    type="time"
                    value={timeValue}
                    onChange={(val) => {
                        const [h, m] = (val || '').split(':').map((n) => parseInt(n, 10))
                        // isFinite (not isNaN) so a cleared/partial input — where h or m is `undefined`,
                        // which isNaN() does not catch — falls back to the default rather than undefined.
                        setActionFormValue('cadence', {
                            ...cadence,
                            hour: Number.isFinite(h) ? h : DEFAULT_CADENCE.hour,
                            minute: Number.isFinite(m) ? m : DEFAULT_CADENCE.minute,
                        })
                    }}
                />
            </div>

            <div>
                <label className="text-sm font-semibold">Timezone</label>
                <TimezoneSelect value={timezone} onChange={(tz) => setActionFormValue('timezone', tz)} />
            </div>

            <span className="text-xs text-muted">{humanizeCadence(cadence)}</span>
            <span className="text-xs text-muted">
                Each run summarizes up to 100 observations from the period. Busier periods are sampled down to that
                limit.
            </span>
        </div>
    )
}

function DeliverySection(): JSX.Element {
    const { actionForm } = useValues(actionEditorSceneLogic)
    const { setActionFormValue } = useActions(actionEditorSceneLogic)
    const { slackIntegrations } = useValues(integrationsLogic)
    const { integration_id } = actionForm

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
                    setActionFormValue('integration_id', value)
                    setActionFormValue('channel', '')
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

export function ActionEditorSceneComponent(): JSX.Element {
    const { isNew, actionLoading, loadedAction, actionForm, isActionFormSubmitting, effectiveScannerId } =
        useValues(actionEditorSceneLogic)

    if (!isNew && actionLoading && !loadedAction) {
        return (
            <SceneContent>
                <SceneTitleSection name="Loading…" resourceType={{ type: 'replay_vision' }} />
            </SceneContent>
        )
    }

    const title = isNew ? 'New action' : loadedAction?.name || 'Edit action'
    const noDays = actionForm.cadence.weekdays.length === 0
    const backTo = isNew
        ? `${urls.replayVision(effectiveScannerId)}?tab=actions`
        : urls.replayVisionAction(loadedAction?.id ?? '')

    return (
        <SceneContent>
            <div className="flex flex-col items-center pt-8 pb-8">
                <div className="w-full max-w-3xl px-4 flex flex-col gap-6">
                    <SceneTitleSection
                        name={title}
                        description="Schedule an AI summary of this scanner's observations and deliver it to Slack."
                        resourceType={{ type: 'replay_vision' }}
                        actions={<ReplayVisionFeedbackButton />}
                    />
                    <Form
                        logic={actionEditorSceneLogic}
                        formKey="actionForm"
                        id="action-editor-form"
                        enableFormOnSubmit
                        className="w-full"
                    >
                        <div className="bg-bg-light border rounded-lg shadow-sm p-6 flex flex-col gap-4">
                            <LemonField name="name" label="Name">
                                <LemonInput placeholder="Daily checkout summary" autoFocus />
                            </LemonField>

                            <div>
                                <h4 className="mb-1">Schedule</h4>
                                <ScheduleSection />
                            </div>

                            <LemonField
                                name="prompt_guide"
                                label="Guidance"
                                info="Optional. Steers how the AI writes the summary."
                            >
                                <LemonTextArea
                                    placeholder="Optional. e.g. focus on issues, bugs, and friction users face — or focus on general user behavior and flows."
                                    maxLength={500}
                                />
                            </LemonField>

                            <div>
                                <h4 className="mb-1">Deliver to Slack</h4>
                                <DeliverySection />
                            </div>

                            <div className="text-xs text-muted">
                                Each scheduled run generates an AI summary using your PostHog AI credits. Runs are
                                skipped while you're over your AI-credit budget.
                            </div>

                            <div className="flex gap-2 justify-end border-t pt-4">
                                <LemonButton type="secondary" to={backTo} data-attr="vision-action-editor-cancel">
                                    Cancel
                                </LemonButton>
                                <LemonButton
                                    type="primary"
                                    htmlType="submit"
                                    form="action-editor-form"
                                    loading={isActionFormSubmitting}
                                    disabledReason={noDays ? 'Pick at least one day to run on' : undefined}
                                    data-attr="vision-action-editor-save"
                                >
                                    {isNew ? 'Create action' : 'Save'}
                                </LemonButton>
                            </div>
                        </div>
                    </Form>
                </div>
            </div>
        </SceneContent>
    )
}

export default ActionEditorSceneComponent
