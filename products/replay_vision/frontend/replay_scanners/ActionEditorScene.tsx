import { useActions, useValues } from 'kea'
import { Form } from 'kea-forms'
import { useMemo } from 'react'

import { LemonButton, LemonInput, LemonInputSelect, LemonSegmentedButton, LemonSelect } from '@posthog/lemon-ui'

import { IntegrationChoice } from 'lib/components/CyclotronJob/integrations/IntegrationChoice'
import { NotFound } from 'lib/components/NotFound'
import { FEATURE_FLAGS } from 'lib/constants'
import { integrationsLogic } from 'lib/integrations/integrationsLogic'
import { SlackChannelPicker, SlackNotConfiguredBanner } from 'lib/integrations/SlackIntegrationHelpers'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { LemonSearchableSelect } from 'lib/lemon-ui/LemonSelect/LemonSearchableSelect'
import { LemonTextArea } from 'lib/lemon-ui/LemonTextArea/LemonTextArea'
import { Spinner, SpinnerOverlay } from 'lib/lemon-ui/Spinner'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { timeZoneLabel } from 'lib/utils/timezones'
import { preflightLogic } from 'scenes/PreflightCheck/preflightLogic'
import { SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'
import { ProductKey } from '~/queries/schema/schema-general'

import { ReplayVisionFeedbackButton } from '../components/ReplayVisionFeedbackButton'
import {
    AlertConfigFrequencyEnumApi,
    VisionActionModeEnumApi,
    VisionAlertDirectionEnumApi,
    VisionAlertMetricEnumApi,
} from '../generated/api.schemas'
import { actionEditorSceneLogic } from './actionEditorSceneLogic'
import { DEFAULT_CADENCE } from './cadence'
import { replayScannerLogic } from './replayScannerLogic'

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

            <span className="text-xs text-muted">
                Each run summarizes up to 100 observations from the period. Busier periods are sampled down to that
                limit.
            </span>
        </div>
    )
}

const VERDICT_OPTIONS: { value: 'yes' | 'no' | 'inconclusive'; label: string }[] = [
    { value: 'yes', label: 'Yes' },
    { value: 'no', label: 'No' },
    { value: 'inconclusive', label: 'Inconclusive' },
]

// Type-specific "what to summarize" controls. Empty controls mean every observation is summarized;
// the selected values narrow it (verdicts for monitors, tags for classifiers, a score range for
// scorers). Summarizers have no outcome to filter on, so the section is hidden entirely.
function TargetingSection({ scannerId }: { scannerId: string }): JSX.Element | null {
    const { actionForm, actionFormErrors, targetingMode } = useValues(actionEditorSceneLogic)
    const { setActionFormValue, setTargetingMode } = useActions(actionEditorSceneLogic)
    const { scanner } = useValues(replayScannerLogic({ id: scannerId }))

    if (!scanner) {
        return null
    }

    const toNumberOrNull = (val: number | undefined): number | null => (val === undefined || isNaN(val) ? null : val)

    let controls: JSX.Element
    switch (scanner.scanner_type) {
        case 'monitor':
            controls = (
                <div className="flex flex-col gap-1">
                    <div className="flex gap-1">
                        {VERDICT_OPTIONS.map(({ value, label }) => (
                            <LemonButton
                                key={value}
                                size="small"
                                type={actionForm.verdict.includes(value) ? 'primary' : 'secondary'}
                                onClick={() =>
                                    setActionFormValue(
                                        'verdict',
                                        actionForm.verdict.includes(value)
                                            ? actionForm.verdict.filter((v) => v !== value)
                                            : [...actionForm.verdict, value]
                                    )
                                }
                                data-attr={`vision-action-targeting-verdict-${value}`}
                            >
                                {label}
                            </LemonButton>
                        ))}
                    </div>
                    <span className="text-xs text-muted">Only summarize observations with these verdicts.</span>
                </div>
            )
            break
        case 'classifier': {
            const configuredTags: string[] = scanner.scanner_config?.tags ?? []
            const allowFreeform = !!scanner.scanner_config?.allow_freeform_tags
            controls = (
                <div className="flex flex-col gap-1">
                    <LemonInputSelect
                        mode="multiple"
                        allowCustomValues={allowFreeform}
                        placeholder="Pick tags…"
                        value={actionForm.tags}
                        onChange={(tags) => setActionFormValue('tags', tags)}
                        options={[...new Set([...configuredTags, ...actionForm.tags])].map((t) => ({
                            key: t,
                            label: t,
                        }))}
                        data-attr="vision-action-targeting-tags"
                    />
                    <span className="text-xs text-muted">Only summarize observations tagged with any of these.</span>
                </div>
            )
            break
        }
        case 'scorer': {
            const scale = scanner.scanner_config?.scale
            controls = (
                <div className="flex flex-col gap-1">
                    <div className="flex items-center gap-2">
                        <LemonInput
                            type="number"
                            placeholder={scale ? String(scale.min) : 'Min'}
                            value={actionForm.min_score ?? undefined}
                            onChange={(val) => setActionFormValue('min_score', toNumberOrNull(val))}
                            className="w-24"
                            data-attr="vision-action-targeting-min-score"
                        />
                        <span className="text-muted">to</span>
                        <LemonInput
                            type="number"
                            placeholder={scale ? String(scale.max) : 'Max'}
                            value={actionForm.max_score ?? undefined}
                            onChange={(val) => setActionFormValue('max_score', toNumberOrNull(val))}
                            className="w-24"
                            data-attr="vision-action-targeting-max-score"
                        />
                    </div>
                    {actionFormErrors?.min_score ? (
                        <span className="text-xs text-danger">{String(actionFormErrors.min_score)}</span>
                    ) : null}
                    <span className="text-xs text-muted">
                        Only summarize observations scored in this range (inclusive
                        {scale ? `; this scanner scores ${scale.min}–${scale.max}` : ''}).
                    </span>
                </div>
            )
            break
        }
        default:
            // Summarizers have no outcome to filter on, so there's nothing to configure here.
            return null
    }

    return (
        <div className="flex flex-col gap-2">
            <h4 className="mb-0">What to summarize</h4>
            <LemonSegmentedButton
                size="small"
                value={targetingMode}
                onChange={(mode) => setTargetingMode(mode)}
                options={[
                    { value: 'all' as const, label: 'All observations' },
                    { value: 'filtered' as const, label: 'Only matching observations' },
                ]}
                data-attr="vision-action-targeting-mode"
            />
            {targetingMode === 'filtered' && controls}
        </div>
    )
}

const WINDOW_OPTIONS = [
    { value: 1, label: 'the last 24 hours' },
    { value: 3, label: 'the last 3 days' },
    { value: 7, label: 'the last 7 days' },
    { value: 14, label: 'the last 14 days' },
    { value: 30, label: 'the last 30 days' },
]

// The type-specific match controls (verdict chips / tag picker / score range), shared by both alert
// flavors. Empty controls mean any observation matches.
function MatchControls({ scannerId }: { scannerId: string }): JSX.Element {
    const { actionForm } = useValues(actionEditorSceneLogic)
    const { setActionFormValue } = useActions(actionEditorSceneLogic)
    const { scanner } = useValues(replayScannerLogic({ id: scannerId }))

    const toNumberOrNull = (val: number | undefined): number | null => (val === undefined || isNaN(val) ? null : val)
    const isAvg = actionForm.alert_metric === VisionAlertMetricEnumApi.AvgScore

    switch (scanner?.scanner_type) {
        case 'monitor':
            return (
                <>
                    <span className="text-sm">with verdict</span>
                    <div className="flex gap-1">
                        {VERDICT_OPTIONS.map(({ value, label }) => (
                            <LemonButton
                                key={value}
                                size="xsmall"
                                type={actionForm.verdict.includes(value) ? 'primary' : 'secondary'}
                                onClick={() =>
                                    setActionFormValue(
                                        'verdict',
                                        actionForm.verdict.includes(value)
                                            ? actionForm.verdict.filter((v) => v !== value)
                                            : [...actionForm.verdict, value]
                                    )
                                }
                                data-attr={`vision-action-alert-verdict-${value}`}
                            >
                                {label}
                            </LemonButton>
                        ))}
                    </div>
                    {actionForm.verdict.length === 0 && <span className="text-sm text-muted">(any verdict)</span>}
                </>
            )
        case 'classifier': {
            const configuredTags: string[] = scanner.scanner_config?.tags ?? []
            const allowFreeform = !!scanner.scanner_config?.allow_freeform_tags
            return (
                <>
                    <span className="text-sm">tagged</span>
                    <div className="min-w-48">
                        <LemonInputSelect
                            mode="multiple"
                            size="small"
                            allowCustomValues={allowFreeform}
                            placeholder="any tag"
                            value={actionForm.tags}
                            onChange={(tags) => setActionFormValue('tags', tags)}
                            options={[...new Set([...configuredTags, ...actionForm.tags])].map((tag) => ({
                                key: tag,
                                label: tag,
                            }))}
                            data-attr="vision-action-alert-tags"
                        />
                    </div>
                </>
            )
        }
        case 'scorer':
            if (isAvg) {
                return <></>
            }
            return (
                <>
                    <span className="text-sm">scored between</span>
                    <LemonInput
                        type="number"
                        size="small"
                        placeholder={scanner.scanner_config?.scale ? String(scanner.scanner_config.scale.min) : 'min'}
                        value={actionForm.min_score ?? undefined}
                        onChange={(val) => setActionFormValue('min_score', toNumberOrNull(val))}
                        className="w-20"
                        data-attr="vision-action-alert-min-score"
                    />
                    <span className="text-sm">and</span>
                    <LemonInput
                        type="number"
                        size="small"
                        placeholder={scanner.scanner_config?.scale ? String(scanner.scanner_config.scale.max) : 'max'}
                        value={actionForm.max_score ?? undefined}
                        onChange={(val) => setActionFormValue('max_score', toNumberOrNull(val))}
                        className="w-20"
                        data-attr="vision-action-alert-max-score"
                    />
                </>
            )
        default:
            return <></>
    }
}

// The alert condition: pick a frequency, then either "every new match" (just the match controls) or
// a threshold sentence over a rolling window.
function ConditionSection({ scannerId }: { scannerId: string }): JSX.Element {
    const { actionForm, actionFormErrors } = useValues(actionEditorSceneLogic)
    const { setActionFormValue } = useActions(actionEditorSceneLogic)
    const { scanner } = useValues(replayScannerLogic({ id: scannerId }))

    const everyMatch = actionForm.alert_frequency === AlertConfigFrequencyEnumApi.EveryMatch
    const isScorer = scanner?.scanner_type === 'scorer'

    // Summarizer observations have no verdict/tags/score to threshold on, so the only sensible
    // alert is "every new summary" — no frequency or threshold controls to configure. The logic
    // normalizes the form to every_match to match (actionEditorSceneLogic.setScannerType).
    if (scanner?.scanner_type === 'summarizer') {
        return (
            <div className="flex flex-col gap-2">
                <span className="text-sm">Get notified about every new summary this scanner produces.</span>
                <span className="text-xs text-muted">
                    Checked every few minutes; each notification covers the new summaries since the last check.
                </span>
            </div>
        )
    }

    return (
        <div className="flex flex-col gap-2">
            <LemonSegmentedButton
                size="small"
                value={actionForm.alert_frequency}
                onChange={(value) => {
                    setActionFormValue('alert_frequency', value)
                    if (value === AlertConfigFrequencyEnumApi.EveryMatch) {
                        // every_match counts new matches; an average makes no sense there.
                        setActionFormValue('alert_metric', VisionAlertMetricEnumApi.Count)
                    }
                }}
                options={[
                    { value: AlertConfigFrequencyEnumApi.EveryMatch, label: 'Every new match' },
                    { value: AlertConfigFrequencyEnumApi.OnBreach, label: 'When a threshold is crossed' },
                ]}
                data-attr="vision-action-alert-frequency"
            />

            {everyMatch ? (
                <div className="flex flex-wrap items-center gap-2">
                    <span className="text-sm">Notify me about every new observation</span>
                    <MatchControls scannerId={scannerId} />
                </div>
            ) : (
                <div className="flex flex-wrap items-center gap-2">
                    <span className="text-sm">Notify me when</span>
                    {isScorer ? (
                        <LemonSelect
                            size="small"
                            value={actionForm.alert_metric}
                            onChange={(value) => value && setActionFormValue('alert_metric', value)}
                            options={[
                                { value: VisionAlertMetricEnumApi.Count, label: 'the number of observations' },
                                { value: VisionAlertMetricEnumApi.AvgScore, label: 'the average score' },
                            ]}
                            data-attr="vision-action-alert-metric"
                        />
                    ) : (
                        <span className="text-sm">the number of observations</span>
                    )}
                    <MatchControls scannerId={scannerId} />
                    <span className="text-sm">over</span>
                    <LemonSelect
                        size="small"
                        value={actionForm.alert_window_days}
                        onChange={(value) => value != null && setActionFormValue('alert_window_days', value)}
                        options={WINDOW_OPTIONS}
                        data-attr="vision-action-alert-window"
                    />
                    <LemonSelect
                        size="small"
                        value={actionForm.alert_direction}
                        onChange={(value) => value && setActionFormValue('alert_direction', value)}
                        options={[
                            { value: VisionAlertDirectionEnumApi.Above, label: 'is at least' },
                            { value: VisionAlertDirectionEnumApi.Below, label: 'is at most' },
                        ]}
                        data-attr="vision-action-alert-direction"
                    />
                    <LemonInput
                        type="number"
                        size="small"
                        value={actionForm.alert_threshold ?? undefined}
                        onChange={(val) =>
                            setActionFormValue('alert_threshold', val === undefined || isNaN(val) ? null : val)
                        }
                        className="w-24"
                        data-attr="vision-action-alert-threshold"
                    />
                </div>
            )}
            {actionFormErrors?.alert_threshold ? (
                <span className="text-xs text-danger">{String(actionFormErrors.alert_threshold)}</span>
            ) : null}
            {actionFormErrors?.min_score ? (
                <span className="text-xs text-danger">{String(actionFormErrors.min_score)}</span>
            ) : null}
            <span className="text-xs text-muted">
                {everyMatch
                    ? 'Checked every few minutes; each notification covers the new matches since the last check.'
                    : "Checked about every hour over a rolling window; you're notified when the condition starts being met, and again only after it clears first."}
            </span>
        </div>
    )
}

function DeliverySection(): JSX.Element {
    const { actionForm } = useValues(actionEditorSceneLogic)
    const { setActionFormValue } = useActions(actionEditorSceneLogic)
    const { slackIntegrations, integrationsLoading } = useValues(integrationsLogic)
    const { integration_id } = actionForm

    if (!slackIntegrations?.length) {
        // Don't flash the "add to Slack" banner (which also builds an authorize URL) while the
        // integrations list is still loading.
        if (integrationsLoading) {
            return <Spinner />
        }
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
            {!actionForm.channel && (
                <span className="text-xs text-muted">
                    No channel selected — this summary will appear on the scanner page and in its run history, without a
                    Slack notification.
                </span>
            )}
        </div>
    )
}

export function ActionEditorSceneComponent(): JSX.Element {
    const { isNew, actionLoading, loadedAction, actionForm, isActionFormSubmitting, effectiveScannerId, scannerName } =
        useValues(actionEditorSceneLogic)
    const { setActionFormValue } = useActions(actionEditorSceneLogic)
    const { featureFlags, receivedFeatureFlags } = useValues(featureFlagLogic)

    if (!featureFlags[FEATURE_FLAGS.REPLAY_VISION] || !featureFlags[FEATURE_FLAGS.REPLAY_VISION_ACTIONS]) {
        // Flags load asynchronously, so wait for them before deciding the page doesn't exist.
        if (!receivedFeatureFlags) {
            return <SpinnerOverlay sceneLevel />
        }
        return <NotFound object="page" />
    }

    if (!isNew && actionLoading && !loadedAction) {
        return (
            <SceneContent>
                <SceneTitleSection name="Loading…" resourceType={{ type: 'replay_vision' }} />
            </SceneContent>
        )
    }

    // Editing but the load failed — don't render a blank form pointing at a broken action.
    if (!isNew && !loadedAction) {
        return (
            <SceneContent>
                <SceneTitleSection name="Summary not found" resourceType={{ type: 'replay_vision' }} />
                <div className="flex justify-center pt-4">
                    <LemonButton type="secondary" to={urls.replayVision()}>
                        Back to Replay vision
                    </LemonButton>
                </div>
            </SceneContent>
        )
    }

    const isAlert = actionForm.mode === VisionActionModeEnumApi.Alert
    const noun = isAlert ? 'alert' : 'group summary'
    const title = isNew
        ? scannerName
            ? `New ${noun} for ${scannerName}`
            : `New ${noun}`
        : loadedAction?.name || `Edit ${noun}`
    const noDays = actionForm.cadence.weekdays.length === 0
    const backTo = isNew
        ? `${urls.replayVision(effectiveScannerId)}?tab=actions`
        : urls.replayVisionAction(loadedAction?.id ?? '')

    return (
        <SceneContent>
            <div className="flex flex-col items-center py-8">
                <div className="w-full max-w-3xl px-4 flex flex-col gap-6">
                    <SceneTitleSection
                        name={title}
                        description={
                            isAlert
                                ? 'Watch this scanner on a schedule and get notified only when the condition is met.'
                                : "Schedule an AI summary of this scanner's observations and deliver it to Slack."
                        }
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
                                <LemonInput
                                    placeholder={isAlert ? 'Rage click alert' : 'Daily checkout summary'}
                                    autoFocus
                                />
                            </LemonField>

                            <div>
                                <h4 className="mb-1">Type</h4>
                                <LemonSegmentedButton
                                    size="small"
                                    value={actionForm.mode}
                                    onChange={(value) => setActionFormValue('mode', value)}
                                    options={[
                                        {
                                            value: VisionActionModeEnumApi.GroupSummary,
                                            label: 'Scheduled group summary',
                                        },
                                        { value: VisionActionModeEnumApi.Alert, label: 'Alert' },
                                    ]}
                                    data-attr="vision-action-mode"
                                />
                            </div>

                            {!isAlert && (
                                <div>
                                    <h4 className="mb-1">Schedule</h4>
                                    <ScheduleSection />
                                </div>
                            )}

                            {!isAlert && effectiveScannerId ? (
                                <TargetingSection scannerId={effectiveScannerId} />
                            ) : null}

                            {isAlert && effectiveScannerId ? (
                                <div>
                                    <h4 className="mb-1">Condition</h4>
                                    <ConditionSection scannerId={effectiveScannerId} />
                                </div>
                            ) : null}

                            {!isAlert && (
                                <LemonField
                                    name="prompt_guide"
                                    label="Additional guidance (optional)"
                                    info="Steers how the AI writes the summary."
                                >
                                    <LemonTextArea
                                        placeholder="e.g. focus on issues, bugs, and friction users face — or focus on general user behavior and flows."
                                        maxLength={500}
                                    />
                                </LemonField>
                            )}

                            <div>
                                <h4 className="mb-1">Deliver to Slack (optional)</h4>
                                <DeliverySection />
                            </div>

                            {!isAlert && (
                                <div className="text-xs text-muted">
                                    Each scheduled run generates an AI summary using your PostHog AI credits. Runs are
                                    skipped while you're over your AI-credit budget.
                                </div>
                            )}

                            <div className="flex gap-2 justify-end border-t pt-4">
                                <LemonButton type="secondary" to={backTo} data-attr="vision-action-editor-cancel">
                                    Cancel
                                </LemonButton>
                                <LemonButton
                                    type="primary"
                                    htmlType="submit"
                                    form="action-editor-form"
                                    loading={isActionFormSubmitting}
                                    disabledReason={!isAlert && noDays ? 'Pick at least one day to run on' : undefined}
                                    data-attr="vision-action-editor-save"
                                >
                                    {isNew ? (isAlert ? 'Create alert' : 'Create summary') : 'Save'}
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
