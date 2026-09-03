import { useValues } from 'kea'

import { LemonInput, LemonInputSelect, LemonSegmentedButton, LemonSelect } from '@posthog/lemon-ui'

import { LemonField } from 'lib/lemon-ui/LemonField'
import { teamLogic } from 'scenes/teamLogic'

import { AlertAdvancedOptions } from 'products/alerts/frontend/components/AlertAdvancedOptions'
import { AlertDefinitionRow } from 'products/alerts/frontend/components/AlertDefinition'
import { AlertEditorSection } from 'products/alerts/frontend/components/AlertEditor'
import { QuietHoursFields } from 'products/alerts/frontend/components/QuietHoursFields'

import { scannerAlertFormLogic } from '../scannerAlertFormLogic'

const WINDOW_OPTIONS = [
    { value: 1, label: '24 hours' },
    { value: 3, label: '3 days' },
    { value: 7, label: '7 days' },
    { value: 14, label: '14 days' },
    { value: 30, label: '30 days' },
]

const MONITOR_VERDICT_OPTIONS = [
    { key: 'yes', label: 'Yes' },
    { key: 'no', label: 'No' },
    { key: 'inconclusive', label: 'Inconclusive' },
]

// Cadence is server-managed (hourly checks); shown to explain when quiet hours apply.
const CHECK_CADENCE_MINUTES = 60

export function ScannerAlertKindPicker(): JSX.Element {
    return (
        <LemonField name="kind" label="Alert type">
            {({ value, onChange }) => (
                <LemonSegmentedButton
                    value={value}
                    onChange={onChange}
                    options={[
                        {
                            value: 'match',
                            label: 'Every matching observation',
                            tooltip: 'Notifies within about a minute of each observation that matches.',
                            'data-attr': 'vision-alert-kind-match',
                        },
                        {
                            value: 'metric',
                            label: 'Metric threshold',
                            tooltip: 'Notifies when a metric over a rolling window crosses a threshold.',
                            'data-attr': 'vision-alert-kind-metric',
                        },
                    ]}
                    fullWidth
                />
            )}
        </LemonField>
    )
}

export function ScannerAlertSelectionFields({ scannerType }: { scannerType?: string }): JSX.Element {
    return (
        <AlertEditorSection
            title="Which observations count"
            description="Leave everything empty to match every observation of this scanner."
        >
            <div className="space-y-3">
                {scannerType === 'monitor' ? (
                    <LemonField name="verdict" label="Verdict">
                        {({ value, onChange }) => (
                            <LemonInputSelect
                                mode="multiple"
                                value={value}
                                onChange={onChange}
                                options={MONITOR_VERDICT_OPTIONS}
                                placeholder="Any verdict"
                                data-attr="vision-alert-verdict"
                            />
                        )}
                    </LemonField>
                ) : null}
                {scannerType === 'classifier' ? (
                    <LemonField name="tags" label="Tags" info="Matches observations carrying any of these tags.">
                        {({ value, onChange }) => (
                            <LemonInputSelect
                                mode="multiple"
                                allowCustomValues
                                value={value}
                                onChange={onChange}
                                options={[]}
                                placeholder="Any tag"
                                data-attr="vision-alert-tags"
                            />
                        )}
                    </LemonField>
                ) : null}
                {scannerType === 'scorer' ? (
                    <div className="flex gap-4">
                        <LemonField name="minScore" label="Minimum score">
                            {({ value, onChange }) => (
                                <LemonInput
                                    type="number"
                                    value={value ?? undefined}
                                    onChange={(v) => onChange(v ?? null)}
                                    placeholder="No minimum"
                                    data-attr="vision-alert-min-score"
                                />
                            )}
                        </LemonField>
                        <LemonField name="maxScore" label="Maximum score">
                            {({ value, onChange }) => (
                                <LemonInput
                                    type="number"
                                    value={value ?? undefined}
                                    onChange={(v) => onChange(v ?? null)}
                                    placeholder="No maximum"
                                    data-attr="vision-alert-max-score"
                                />
                            )}
                        </LemonField>
                    </div>
                ) : null}
            </div>
        </AlertEditorSection>
    )
}

export function ScannerAlertTrigger({ thresholdError }: { thresholdError?: string } = {}): JSX.Element {
    const { alertForm } = useValues(scannerAlertFormLogic)
    const { currentTeam } = useValues(teamLogic)

    if (alertForm.kind !== 'metric') {
        return (
            <AlertEditorSection title="When it fires">
                <div className="space-y-4">
                    <p className="text-muted mb-0">
                        You get one bundled notification per minute covering every new matching observation, so a burst
                        of matches sends one message instead of many.
                    </p>
                    <AlertAdvancedOptions>
                        <LemonField name="scheduleRestriction">
                            {({ value, onChange }) => (
                                <QuietHoursFields
                                    scheduleRestriction={value}
                                    cadenceMinutes={CHECK_CADENCE_MINUTES}
                                    teamTimezone={currentTeam?.timezone ?? 'UTC'}
                                    onChange={onChange}
                                />
                            )}
                        </LemonField>
                    </AlertAdvancedOptions>
                </div>
            </AlertEditorSection>
        )
    }

    return (
        <AlertEditorSection title="When it fires">
            <div className="space-y-4">
                <AlertDefinitionRow label="Measure">
                    <LemonField name="metric">
                        {({ value, onChange }) => (
                            <LemonSelect
                                value={value}
                                onChange={onChange}
                                options={[
                                    { value: 'count', label: 'number of matching observations' },
                                    { value: 'avg_score', label: 'average score' },
                                ]}
                                data-attr="vision-alert-metric"
                            />
                        )}
                    </LemonField>
                </AlertDefinitionRow>
                <AlertDefinitionRow label="Alert if it is">
                    <LemonField name="direction">
                        {({ value, onChange }) => (
                            <LemonSelect
                                value={value}
                                onChange={onChange}
                                options={[
                                    { value: 'above', label: 'at or above' },
                                    { value: 'below', label: 'at or below' },
                                ]}
                                data-attr="vision-alert-direction"
                            />
                        )}
                    </LemonField>
                    <LemonField name="threshold">
                        {({ value, onChange }) => (
                            <LemonInput
                                type="number"
                                value={value ?? undefined}
                                onChange={(v) => onChange(v ?? null)}
                                className="w-24"
                                status={thresholdError ? 'danger' : undefined}
                                data-attr="vision-alert-threshold"
                            />
                        )}
                    </LemonField>
                    <span>in the last</span>
                    <LemonField name="windowDays">
                        {({ value, onChange }) => (
                            <LemonSelect
                                value={value}
                                onChange={onChange}
                                options={WINDOW_OPTIONS}
                                data-attr="vision-alert-window"
                            />
                        )}
                    </LemonField>
                </AlertDefinitionRow>
                {thresholdError ? <LemonField.Error error={thresholdError} /> : null}

                <AlertAdvancedOptions>
                    <LemonField.Pure
                        label="Noise reduction"
                        info="How many of the recent checks must breach before the alert fires (N of M)."
                    >
                        <div className="flex items-center gap-2">
                            <LemonField name="datapointsToAlarm">
                                {({ value, onChange }) => (
                                    <LemonInput type="number" min={1} max={10} value={value} onChange={onChange} />
                                )}
                            </LemonField>
                            <span>of</span>
                            <LemonField name="evaluationPeriods">
                                {({ value, onChange }) => (
                                    <LemonInput type="number" min={1} max={10} value={value} onChange={onChange} />
                                )}
                            </LemonField>
                            <span>checks must breach</span>
                        </div>
                    </LemonField.Pure>
                    <LemonField.Pure
                        label="Notification cooldown"
                        info="Minimum minutes between repeated notifications. 0 means no cooldown."
                    >
                        <LemonField name="cooldownMinutes">
                            {({ value, onChange }) => (
                                <LemonInput type="number" min={0} value={value} onChange={onChange} className="w-24" />
                            )}
                        </LemonField>
                    </LemonField.Pure>
                    <LemonField name="scheduleRestriction">
                        {({ value, onChange }) => (
                            <QuietHoursFields
                                scheduleRestriction={value}
                                cadenceMinutes={CHECK_CADENCE_MINUTES}
                                teamTimezone={currentTeam?.timezone ?? 'UTC'}
                                onChange={onChange}
                            />
                        )}
                    </LemonField>
                </AlertAdvancedOptions>
            </div>
        </AlertEditorSection>
    )
}
