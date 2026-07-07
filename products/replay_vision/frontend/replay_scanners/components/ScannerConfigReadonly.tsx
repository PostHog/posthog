import { useActions, useValues } from 'kea'

import { IconBolt, IconClock, IconGraph, IconInfo, IconPencil, IconPeople } from '@posthog/icons'
import { LemonCard, LemonSwitch, LemonTag } from '@posthog/lemon-ui'

import { AccessControlAction } from 'lib/components/AccessControlAction'
import { TZLabel } from 'lib/components/TZLabel'
import { UniversalFilterButton } from 'lib/components/UniversalFilters/UniversalFilterButton'
import { ProfilePicture } from 'lib/lemon-ui/ProfilePicture'
import { humanFriendlyDurationFilter } from 'scenes/session-recordings/filters/DurationFilter'
import {
    deriveOperand,
    recordingsQueryToUniversalFilters,
} from 'scenes/session-recordings/filters/recordingsQueryConversions'
import { filtersFromUniversalFilterGroups } from 'scenes/session-recordings/utils'

import { RecordingsQuery } from '~/queries/schema/schema-general'
import { AccessControlLevel, AccessControlResourceType, FilterLogicalOperator } from '~/types'

import { BooleanTag } from '../../components/BooleanTag'
import { CardHeader } from '../../components/CardHeader'
import { LabeledRow } from '../../components/LabeledRow'
import { ScannerTypeBadge } from '../../components/ScannerTypeBadge'
import { replayScannerLogic } from '../replayScannerLogic'
import { MODEL_OPTIONS, ReplayScanner, SAMPLING_MODE_OPTIONS, ScannerType } from '../types'

const SUMMARY_LENGTHS = [
    { value: 'short', label: 'Short' },
    { value: 'medium', label: 'Medium' },
    { value: 'long', label: 'Long' },
] as const

const SCANNER_TYPES: ScannerType[] = ['monitor', 'classifier', 'scorer', 'summarizer']

function Multiline({ value }: { value: string | null | undefined }): JSX.Element {
    return <div className="whitespace-pre-wrap text-sm">{value || <span className="text-muted">—</span>}</div>
}

/** Renders an option set as tags with the chosen value emphasized and the rest greyed/struck through. */
function OptionTags({
    options,
    selected,
}: {
    options: readonly { value: string; label: string }[]
    selected: string | null | undefined
}): JSX.Element {
    return (
        <div className="flex flex-wrap gap-1">
            {options.map((option) => {
                const isSelected = selected === option.value
                return (
                    <LemonTag
                        key={option.value}
                        size="medium"
                        type={isSelected ? 'option' : 'default'}
                        className={isSelected ? undefined : 'opacity-50 line-through'}
                    >
                        {option.label}
                    </LemonTag>
                )
            })}
        </div>
    )
}

function BehaviorCardContent({ scanner }: { scanner: ReplayScanner }): JSX.Element {
    return (
        <>
            <LabeledRow label="Prompt">
                {scanner.scanner_config.prompt ? (
                    <div className="whitespace-pre-wrap text-sm bg-surface-secondary border rounded p-2">
                        {scanner.scanner_config.prompt}
                    </div>
                ) : (
                    <span className="text-muted">—</span>
                )}
            </LabeledRow>
            {scanner.scanner_type === 'summarizer' && (
                <LabeledRow label="Summary length">
                    <OptionTags options={SUMMARY_LENGTHS} selected={scanner.scanner_config.length} />
                </LabeledRow>
            )}
            {scanner.scanner_type === 'monitor' && (
                <LabeledRow label="Allow inconclusive verdicts">
                    <BooleanTag value={!!scanner.scanner_config.allow_inconclusive} />
                </LabeledRow>
            )}
            {scanner.scanner_type === 'classifier' && (
                <>
                    <LabeledRow label="Tag vocabulary">
                        {scanner.scanner_config.tags.length ? (
                            <div className="flex flex-wrap gap-1">
                                {scanner.scanner_config.tags.map((tag) => (
                                    <LemonTag key={tag} type="option">
                                        {tag}
                                    </LemonTag>
                                ))}
                            </div>
                        ) : (
                            <span className="text-muted">—</span>
                        )}
                    </LabeledRow>
                    <LabeledRow label="Multiple tags per session">
                        <BooleanTag value={!!scanner.scanner_config.multi_label} />
                    </LabeledRow>
                    <LabeledRow label="Freeform tags">
                        <BooleanTag value={!!scanner.scanner_config.allow_freeform_tags} />
                    </LabeledRow>
                </>
            )}
            {scanner.scanner_type === 'scorer' && (
                <LabeledRow label="Scale">
                    {scanner.scanner_config.scale.min} – {scanner.scanner_config.scale.max}
                    {scanner.scanner_config.scale.label ? ` (${scanner.scanner_config.scale.label})` : ''}
                </LabeledRow>
            )}
            <LabeledRow label="Emit signals">
                <BooleanTag value={scanner.emits_signals} />
            </LabeledRow>
        </>
    )
}

export function ScannerConfigReadonly({ scanner }: { scanner: ReplayScanner }): JSX.Element {
    const { observationStats, togglingEnabled } = useValues(replayScannerLogic({ id: scanner.id }))
    const { toggleEnabled } = useActions(replayScannerLogic({ id: scanner.id }))
    const samplingPercent = Math.round((scanner.sampling_rate ?? 0) * 1000) / 10
    // Read every filter dimension (events, actions, properties, console logs, …), not just top-level properties.
    const universal = recordingsQueryToUniversalFilters((scanner.query ?? null) as RecordingsQuery | null)
    const filters = filtersFromUniversalFilterGroups(universal)
    const hasTriggers = filters.length > 0 || universal.duration.length > 0 || universal.filter_test_accounts
    const matchWord = deriveOperand(universal.filter_group) === FilterLogicalOperator.Or ? 'any' : 'all'

    return (
        <div className="flex flex-col gap-4">
            <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
                <LemonCard className="p-4" hoverEffect={false}>
                    <CardHeader icon={<IconInfo />} title="Overview" />
                    <div className="flex flex-col gap-3">
                        <LabeledRow label="Type">
                            <div className="flex flex-wrap gap-1">
                                {SCANNER_TYPES.map((scannerType) => (
                                    <ScannerTypeBadge
                                        key={scannerType}
                                        scannerType={scannerType}
                                        variant={scanner.scanner_type === scannerType ? 'default' : 'deemphasized'}
                                    />
                                ))}
                            </div>
                        </LabeledRow>
                        <LabeledRow label="Description">
                            <Multiline value={scanner.description} />
                        </LabeledRow>
                        <LabeledRow label="Model">
                            <OptionTags options={MODEL_OPTIONS} selected={scanner.model} />
                        </LabeledRow>
                        <LabeledRow label="Status">
                            <div className="flex items-center gap-2">
                                <AccessControlAction
                                    resourceType={AccessControlResourceType.SessionRecording}
                                    minAccessLevel={AccessControlLevel.Editor}
                                >
                                    <LemonSwitch
                                        checked={scanner.enabled}
                                        onChange={() => toggleEnabled()}
                                        loading={togglingEnabled}
                                        data-attr="vision-scanner-toggle-enabled"
                                        data-ph-capture-attribute-scanner-type={scanner.scanner_type}
                                        data-ph-capture-attribute-will-be-enabled={!scanner.enabled}
                                    />
                                </AccessControlAction>
                                <span className="text-muted text-xs">
                                    {scanner.enabled ? 'Runs automatically on a schedule' : 'Runs on-demand only'}
                                </span>
                            </div>
                        </LabeledRow>
                    </div>
                </LemonCard>

                <LemonCard className="p-4" hoverEffect={false}>
                    <CardHeader icon={<IconPencil />} title="Behavior" />
                    <div className="flex flex-col gap-3">
                        <BehaviorCardContent scanner={scanner} />
                    </div>
                </LemonCard>
            </div>

            <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
                <LemonCard className="p-4" hoverEffect={false}>
                    <CardHeader icon={<IconBolt />} title="Triggers" />
                    <div className="flex flex-col gap-3">
                        <LabeledRow label="Session coverage">
                            {SAMPLING_MODE_OPTIONS.find((o) => o.value === scanner.sampling_mode)?.label ??
                                scanner.sampling_mode}
                        </LabeledRow>
                        <LabeledRow label="Sampling">{samplingPercent}%</LabeledRow>
                        <LabeledRow label="Recording filters">
                            {!hasTriggers ? (
                                <span className="text-muted">No filters</span>
                            ) : (
                                <div className="flex flex-col gap-2">
                                    {filters.length > 0 && (
                                        <div className="flex flex-wrap items-center gap-1.5">
                                            {filters.length > 1 && (
                                                <span className="text-xs">Match {matchWord} of</span>
                                            )}
                                            {filters.map((filter, i) => (
                                                <UniversalFilterButton key={i} filter={filter} />
                                            ))}
                                        </div>
                                    )}
                                    {(universal.duration.length > 0 || universal.filter_test_accounts) && (
                                        <div className="flex flex-wrap items-center gap-1.5">
                                            {universal.duration.map((duration, i) => (
                                                <LemonTag key={i} type="default" icon={<IconClock />}>
                                                    {humanFriendlyDurationFilter(duration, duration.key)}
                                                </LemonTag>
                                            ))}
                                            {universal.filter_test_accounts && (
                                                <LemonTag type="default" icon={<IconPeople />}>
                                                    No internal/test users
                                                </LemonTag>
                                            )}
                                        </div>
                                    )}
                                </div>
                            )}
                        </LabeledRow>
                    </div>
                </LemonCard>

                <LemonCard className="p-4" hoverEffect={false}>
                    <CardHeader icon={<IconClock />} title="Lifecycle" />
                    <div className="flex flex-col gap-3">
                        <LabeledRow label="Created by">
                            {scanner.created_by ? (
                                <ProfilePicture
                                    user={{
                                        first_name: scanner.created_by.first_name,
                                        last_name: scanner.created_by.last_name,
                                        email: scanner.created_by.email,
                                    }}
                                    size="md"
                                    showName
                                />
                            ) : (
                                <span className="text-muted">—</span>
                            )}
                        </LabeledRow>
                        <LabeledRow label="Created">
                            <TZLabel time={scanner.created_at} />
                        </LabeledRow>
                        <LabeledRow label="Last updated">
                            <TZLabel time={scanner.updated_at} />
                        </LabeledRow>
                        <LabeledRow label="Last scheduled scan">
                            {scanner.last_swept_at ? (
                                <TZLabel time={scanner.last_swept_at} />
                            ) : (
                                <span className="text-muted">Never</span>
                            )}
                        </LabeledRow>
                    </div>
                </LemonCard>

                <LemonCard className="p-4" hoverEffect={false}>
                    <CardHeader icon={<IconGraph />} title="Usage" />
                    <div className="flex flex-col gap-3">
                        <LabeledRow label="Estimated monthly observations">
                            {scanner.estimated_monthly_observations != null ? (
                                <span className="tabular-nums">
                                    {scanner.estimated_monthly_observations.toLocaleString()}
                                </span>
                            ) : (
                                <span className="text-muted">—</span>
                            )}
                        </LabeledRow>
                        <LabeledRow label="Total observations">
                            <span className="tabular-nums">{observationStats.total.toLocaleString()}</span>
                        </LabeledRow>
                        <LabeledRow label="Success rate">
                            {observationStats.successRate != null ? (
                                <span className="tabular-nums">{observationStats.successRate}%</span>
                            ) : (
                                <span className="text-muted">—</span>
                            )}
                        </LabeledRow>
                        <LabeledRow label="Outcomes">
                            <span className="text-sm">
                                {observationStats.succeeded.toLocaleString()} succeeded ·{' '}
                                {observationStats.failed.toLocaleString()} failed ·{' '}
                                {observationStats.ineligible.toLocaleString()} ineligible
                            </span>
                        </LabeledRow>
                    </div>
                </LemonCard>
            </div>
        </div>
    )
}
