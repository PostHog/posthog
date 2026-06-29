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
import { ScannerTypeBadge } from '../../components/ScannerTypeBadge'
import { replayScannerLogic } from '../replayScannerLogic'
import { MODEL_OPTIONS, ReplayScanner, ScannerType } from '../types'

const SUMMARY_LENGTHS = [
    { value: 'short', label: 'Short' },
    { value: 'medium', label: 'Medium' },
    { value: 'long', label: 'Long' },
] as const

const SCANNER_TYPES: ScannerType[] = ['monitor', 'classifier', 'scorer', 'summarizer']

function Row({ label, children }: { label: string; children: React.ReactNode }): JSX.Element {
    return (
        <div>
            <div className="text-xs text-muted mb-0.5">{label}</div>
            <div className="text-sm">{children}</div>
        </div>
    )
}

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
            <Row label="Prompt">
                {scanner.scanner_config.prompt ? (
                    <div className="whitespace-pre-wrap text-sm bg-surface-secondary border rounded p-2">
                        {scanner.scanner_config.prompt}
                    </div>
                ) : (
                    <span className="text-muted">—</span>
                )}
            </Row>
            {scanner.scanner_type === 'summarizer' && (
                <Row label="Summary length">
                    <OptionTags options={SUMMARY_LENGTHS} selected={scanner.scanner_config.length} />
                </Row>
            )}
            {scanner.scanner_type === 'monitor' && (
                <Row label="Allow inconclusive verdicts">
                    <BooleanTag value={!!scanner.scanner_config.allow_inconclusive} />
                </Row>
            )}
            {scanner.scanner_type === 'classifier' && (
                <>
                    <Row label="Tag vocabulary">
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
                    </Row>
                    <Row label="Multiple tags per session">
                        <BooleanTag value={!!scanner.scanner_config.multi_label} />
                    </Row>
                    <Row label="Freeform tags">
                        <BooleanTag value={!!scanner.scanner_config.allow_freeform_tags} />
                    </Row>
                </>
            )}
            {scanner.scanner_type === 'scorer' && (
                <Row label="Scale">
                    {scanner.scanner_config.scale.min} – {scanner.scanner_config.scale.max}
                    {scanner.scanner_config.scale.label ? ` (${scanner.scanner_config.scale.label})` : ''}
                </Row>
            )}
            <Row label="Emit signals">
                <BooleanTag value={scanner.emits_signals} />
            </Row>
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
                        <Row label="Type">
                            <div className="flex flex-wrap gap-1">
                                {SCANNER_TYPES.map((scannerType) => (
                                    <ScannerTypeBadge
                                        key={scannerType}
                                        scannerType={scannerType}
                                        variant={scanner.scanner_type === scannerType ? 'default' : 'deemphasized'}
                                    />
                                ))}
                            </div>
                        </Row>
                        <Row label="Description">
                            <Multiline value={scanner.description} />
                        </Row>
                        <Row label="Model">
                            <OptionTags options={MODEL_OPTIONS} selected={scanner.model} />
                        </Row>
                        <Row label="Status">
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
                        </Row>
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
                        <Row label="Sampling">{samplingPercent}%</Row>
                        <Row label="Recording filters">
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
                        </Row>
                    </div>
                </LemonCard>

                <LemonCard className="p-4" hoverEffect={false}>
                    <CardHeader icon={<IconClock />} title="Lifecycle" />
                    <div className="flex flex-col gap-3">
                        <Row label="Created by">
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
                        </Row>
                        <Row label="Created">
                            <TZLabel time={scanner.created_at} />
                        </Row>
                        <Row label="Last updated">
                            <TZLabel time={scanner.updated_at} />
                        </Row>
                        <Row label="Last scheduled scan">
                            {scanner.last_swept_at ? (
                                <TZLabel time={scanner.last_swept_at} />
                            ) : (
                                <span className="text-muted">Never</span>
                            )}
                        </Row>
                    </div>
                </LemonCard>

                <LemonCard className="p-4" hoverEffect={false}>
                    <CardHeader icon={<IconGraph />} title="Usage" />
                    <div className="flex flex-col gap-3">
                        <Row label="Estimated monthly observations">
                            {scanner.estimated_monthly_observations != null ? (
                                <span className="tabular-nums">
                                    {scanner.estimated_monthly_observations.toLocaleString()}
                                </span>
                            ) : (
                                <span className="text-muted">—</span>
                            )}
                        </Row>
                        <Row label="Total observations">
                            <span className="tabular-nums">{observationStats.total.toLocaleString()}</span>
                        </Row>
                        <Row label="Success rate">
                            {observationStats.successRate != null ? (
                                <span className="tabular-nums">{observationStats.successRate}%</span>
                            ) : (
                                <span className="text-muted">—</span>
                            )}
                        </Row>
                        <Row label="Outcomes">
                            <span className="text-sm">
                                {observationStats.succeeded.toLocaleString()} succeeded ·{' '}
                                {observationStats.failed.toLocaleString()} failed ·{' '}
                                {observationStats.ineligible.toLocaleString()} ineligible
                            </span>
                        </Row>
                    </div>
                </LemonCard>
            </div>
        </div>
    )
}
