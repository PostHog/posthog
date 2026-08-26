import { useActions, useValues } from 'kea'
import { Fragment } from 'react'

import {
    IconBolt,
    IconClock,
    IconGraph,
    IconInfo,
    IconPencil,
    IconPeople,
    IconThumbsDownFilled,
    IconThumbsUpFilled,
} from '@posthog/icons'
import { LemonCard, LemonCollapse, LemonSwitch, LemonTag } from '@posthog/lemon-ui'

import { PropertyFilterButton } from 'lib/components/PropertyFilters/components/PropertyFilterButton'
import { TZLabel } from 'lib/components/TZLabel'
import { UniversalFilterButton } from 'lib/components/UniversalFilters/UniversalFilterButton'
import { isEntityFilter } from 'lib/components/UniversalFilters/utils'
import { FEATURE_FLAGS } from 'lib/constants'
import { dayjs } from 'lib/dayjs'
import { ProfilePicture } from 'lib/lemon-ui/ProfilePicture'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { themeLogic } from 'lib/logic/themeLogic'
import { humanFriendlyDurationFilter } from 'scenes/session-recordings/filters/DurationFilter'
import {
    deriveOperand,
    recordingsQueryToUniversalFilters,
} from 'scenes/session-recordings/filters/recordingsQueryConversions'
import { filtersFromUniversalFilterGroups } from 'scenes/session-recordings/utils'

import { RecordingsQuery } from '~/queries/schema/schema-general'
import { FilterLogicalOperator, UniversalFilterValue } from '~/types'

import { BooleanTag } from '../../components/BooleanTag'
import { CardHeader } from '../../components/CardHeader'
import { LabeledRow } from '../../components/LabeledRow'
import { CreditPriceNote } from '../../components/PricingLink'
import { ScannerTypeBadge } from '../../components/ScannerTypeBadge'
import { visionQuotaLogic } from '../../logics/visionQuotaLogic'
import { getReplayVisionEditDisabledReason } from '../../utils/accessControl'
import { formatCreditsMaybeUsd } from '../../utils/credits'
import { replayScannerLogic } from '../replayScannerLogic'
import {
    ReplayScanner,
    SAMPLING_MODE_OPTIONS,
    ScannerType,
    getModelOptions,
    modelLabel,
    modelNamingVariant,
    scannerTypeLabel,
} from '../types'
import { FieldCurrentValue } from './ConfigChangeCards'
import { fieldEditor } from './configChanges'
import { PromptDiffButton } from './PromptDiff'
import {
    VersionChanges,
    VersionConfig,
    versionChangesByVersion,
    versionConfigFromMarker,
    versionConfigFromScanner,
} from './versionChanges'

const SUMMARY_LENGTHS = [
    { value: 'short', label: 'Short' },
    { value: 'medium', label: 'Medium' },
    { value: 'long', label: 'Long' },
] as const

const SCANNER_TYPES: ScannerType[] = ['monitor', 'classifier', 'scorer', 'summarizer']

/** The recording filters a query selects on: events, actions, properties, console logs, duration, test accounts. */
function RecordingFilters({ query }: { query: unknown }): JSX.Element {
    // Read every filter dimension, not just top-level properties.
    const universal = recordingsQueryToUniversalFilters((query ?? null) as RecordingsQuery | null)
    const filters = filtersFromUniversalFilterGroups(universal)
    if (filters.length === 0 && universal.duration.length === 0 && !universal.filter_test_accounts) {
        return <span className="text-muted">No filters</span>
    }
    const matchWord = deriveOperand(universal.filter_group) === FilterLogicalOperator.Or ? 'any' : 'all'
    return (
        <div className="flex flex-col gap-2">
            {filters.length > 0 && (
                <div className="flex flex-wrap items-center gap-1.5">
                    {filters.length > 1 && <span className="text-xs">Match {matchWord} of</span>}
                    {filters.map((filter, i) => (
                        <ReadonlyFilter key={i} filter={filter} />
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

/** One recording filter, read-only. An event or action filter carries its own property filters, which the
 * editable UI keeps behind a popover — there's nothing to open here, so show them alongside the event. */
function ReadonlyFilter({ filter }: { filter: UniversalFilterValue }): JSX.Element {
    const properties = isEntityFilter(filter) ? (filter.properties ?? []) : []
    return (
        <div className="flex flex-wrap items-center gap-1.5">
            <UniversalFilterButton filter={filter} />
            {properties.length > 0 && (
                <>
                    <span className="text-xs">where</span>
                    {properties.map((property, i) => (
                        <PropertyFilterButton key={i} item={property} compact />
                    ))}
                </>
            )}
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
                    <LabeledRow label="Categories">
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
                    <LabeledRow label="Multiple categories per session">
                        <BooleanTag value={!!scanner.scanner_config.multi_label} />
                    </LabeledRow>
                    <LabeledRow label="Freeform categories">
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

/** What a version changed, field by field. Versions bump on any tracked change, so without this a bump the
 * reader can't spot (a flag, the model, sampling) reads as a no-op. */
function VersionChangeSummary({
    changes,
    version,
    isDarkModeOn,
}: {
    changes: VersionChanges
    version: number
    isDarkModeOn: boolean
}): JSX.Element {
    const comparedWith = changes.previous.version
    return (
        <div className="rounded bg-surface-secondary px-3 py-2 space-y-1">
            <div className="text-xs font-medium">
                {changes.changes.length > 0
                    ? `Changed since v${comparedWith}`
                    : `Nothing recorded for v${version} differs from v${comparedWith}`}
            </div>
            {changes.changes.map((change) => (
                <div key={change.field} className="flex flex-wrap items-baseline gap-x-2 text-xs">
                    <span className="text-muted">{change.label}</span>
                    {change.kind === 'value' ? (
                        <span>
                            <span className="text-muted line-through">{change.before}</span>
                            <span className="text-muted mx-1">→</span>
                            {change.after}
                        </span>
                    ) : (
                        <span className="flex items-center gap-2">
                            <span>edited</span>
                            {change.kind === 'prompt' && (
                                <PromptDiffButton
                                    original={change.before}
                                    modified={change.after}
                                    originalTitle={`v${comparedWith}`}
                                    modifiedTitle={`v${version}`}
                                    isDarkModeOn={isDarkModeOn}
                                />
                            )}
                        </span>
                    )}
                </div>
            ))}
            {changes.notRecorded.length > 0 && (
                <div className="text-xs text-muted">
                    {changes.notRecorded.join(', ')} weren't recorded for these versions, so a change there isn't shown.
                </div>
            )}
        </div>
    )
}

/** Every version-tracked field the version ran with, so the reader sees the whole config, not only the diff. */
function VersionFields({ config, changed }: { config: VersionConfig; changed: Set<string> }): JSX.Element {
    // A field the run snapshots never carried must say so, not render a default that reads as a real value.
    const recorded = (value: unknown, render: () => JSX.Element): JSX.Element =>
        value == null ? <span className="text-muted">Not recorded</span> : render()
    const rows: { field: string; label: string; value: JSX.Element }[] = [
        {
            field: 'prompt',
            label: 'Prompt',
            value: (
                <div className="whitespace-pre-wrap">
                    {String(config.scannerConfig.prompt ?? '') || <span className="text-muted">—</span>}
                </div>
            ),
        },
        {
            field: 'scannerType',
            label: 'Type',
            value: recorded(config.scannerType, () => (
                <span>{scannerTypeLabel(config.scannerType as ScannerType)}</span>
            )),
        },
        {
            field: 'model',
            label: 'Model',
            value: recorded(config.model, () => <span>{modelLabel(config.model)}</span>),
        },
        {
            field: 'provider',
            label: 'Provider',
            value: recorded(config.provider, () => <span>{config.provider}</span>),
        },
        {
            field: 'emitsSignals',
            label: 'Emit signals',
            value: recorded(config.emitsSignals, () => <BooleanTag value={!!config.emitsSignals} />),
        },
        {
            field: 'samplingMode',
            label: 'Session coverage',
            value: recorded(config.samplingMode, () => (
                <span>
                    {SAMPLING_MODE_OPTIONS.find((option) => option.value === config.samplingMode)?.label ??
                        config.samplingMode}
                </span>
            )),
        },
        {
            field: 'samplingRate',
            label: 'Sampling',
            value: recorded(config.samplingRate, () => (
                <span>{Math.round((config.samplingRate ?? 0) * 1000) / 10}%</span>
            )),
        },
        ...Object.keys(config.scannerConfig)
            .filter((key) => key !== 'prompt')
            .map((key) => {
                const { kind, label } = fieldEditor(key, config.scannerConfig[key])
                return { field: key, label, value: <FieldCurrentValue kind={kind} value={config.scannerConfig[key]} /> }
            }),
        {
            field: 'query',
            label: 'Recording filters',
            value: recorded(config.query, () => <RecordingFilters query={config.query} />),
        },
    ]
    return (
        <div className="grid grid-cols-[auto_1fr] items-baseline gap-x-3 gap-y-1.5 text-xs">
            {rows.map((row) => (
                <Fragment key={row.field}>
                    <span className="text-muted">{row.label}</span>
                    {/* Emphasis suits a short value, not a whole prompt. The change summary flags that one. */}
                    <span className={changed.has(row.field) && row.field !== 'prompt' ? 'font-medium' : undefined}>
                        {row.value}
                    </span>
                </Fragment>
            ))}
        </div>
    )
}

function ConfigVersionHistory({ scanner }: { scanner: ReplayScanner }): JSX.Element | null {
    const { observationStatsApi } = useValues(replayScannerLogic({ id: scanner.id }))
    const { isDarkModeOn } = useValues(themeLogic)
    const markers = observationStatsApi?.labels.version_markers ?? []
    const currentVersion = scanner.scanner_version
    const hasCurrentMarker = markers.some((marker) => marker.version === currentVersion)
    if (markers.length === 0 && !hasCurrentMarker && !scanner.scanner_config.prompt) {
        return null
    }
    const byVersion = new Map(markers.map((marker) => [marker.version, marker]))
    // A version saved but not yet scanned has no marker, so the live scanner stands in for it.
    const configs = markers.map(versionConfigFromMarker)
    if (!hasCurrentMarker) {
        configs.push(versionConfigFromScanner(scanner))
    }
    const changesByVersion = versionChangesByVersion(configs)
    const newestFirst = [...configs].sort((a, b) => b.version - a.version)
    return (
        <LemonCard className="p-4" hoverEffect={false}>
            <CardHeader icon={<IconPencil />} title="Config versions" />
            <div className="flex flex-col gap-3">
                {newestFirst.map((config) => {
                    const marker = byVersion.get(config.version)
                    const changes = changesByVersion.get(config.version)
                    return (
                        <div
                            key={config.version}
                            className="border rounded p-3 space-y-2"
                            id={`prompt-v${config.version}`}
                        >
                            <div className="flex flex-wrap items-center gap-2 text-xs text-muted">
                                <LemonTag
                                    type={config.version === currentVersion ? 'warning' : 'muted'}
                                    className="font-mono"
                                >
                                    v{config.version}
                                </LemonTag>
                                {marker ? (
                                    <>
                                        <span>from {dayjs(marker.date).format('MMM D, YYYY')}</span>
                                        <span className="flex items-center gap-1">
                                            <IconThumbsUpFilled className="text-success" /> {marker.up}
                                        </span>
                                        <span className="flex items-center gap-1">
                                            <IconThumbsDownFilled className="text-danger" /> {marker.down}
                                        </span>
                                    </>
                                ) : (
                                    <span>current · no scans yet</span>
                                )}
                            </div>
                            {changes ? (
                                <VersionChangeSummary
                                    changes={changes}
                                    version={config.version}
                                    isDarkModeOn={isDarkModeOn}
                                />
                            ) : (
                                <div className="text-xs text-muted">Oldest version with scans.</div>
                            )}
                            {/* Collapsed by default: the summary above already names what changed, so the
                                full config is only needed when someone wants the rest of it. */}
                            <LemonCollapse
                                embedded
                                size="xsmall"
                                panels={[
                                    {
                                        key: 'config',
                                        header: 'Full config',
                                        content: (
                                            <VersionFields
                                                config={config}
                                                changed={
                                                    new Set((changes?.changes ?? []).map((change) => change.field))
                                                }
                                            />
                                        ),
                                    },
                                ]}
                            />
                        </div>
                    )
                })}
            </div>
        </LemonCard>
    )
}

export function ScannerConfigReadonly({ scanner }: { scanner: ReplayScanner }): JSX.Element {
    const { observationStats, togglingEnabled } = useValues(replayScannerLogic({ id: scanner.id }))
    const { showUsd } = useValues(visionQuotaLogic)
    const { toggleEnabled } = useActions(replayScannerLogic({ id: scanner.id }))
    const { featureFlags } = useValues(featureFlagLogic)
    const namingVariant = modelNamingVariant(featureFlags[FEATURE_FLAGS.REPLAY_VISION_MODEL_TIER_NAMING_EXPERIMENT])
    const samplingPercent = Math.round((scanner.sampling_rate ?? 0) * 1000) / 10

    return (
        <div className="flex flex-col gap-4">
            <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
                <div className="flex flex-col gap-4">
                    <div className="rounded border p-4 bg-bg-light flex flex-col gap-2">
                        <LemonSwitch
                            checked={scanner.enabled}
                            onChange={() => toggleEnabled()}
                            loading={togglingEnabled}
                            disabledReason={getReplayVisionEditDisabledReason(scanner.user_access_level)}
                            label="Enable scanner"
                            bordered
                            fullWidth
                            data-attr="vision-scanner-toggle-enabled"
                            data-ph-capture-attribute-scanner-type={scanner.scanner_type}
                            data-ph-capture-attribute-will-be-enabled={!scanner.enabled}
                        />
                        <span className="text-muted text-xs">
                            {scanner.enabled ? 'Runs automatically on a schedule' : 'Runs on-demand only'}
                        </span>
                    </div>
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
                                <OptionTags options={getModelOptions(namingVariant)} selected={scanner.model} />
                            </LabeledRow>
                        </div>
                    </LemonCard>
                </div>

                <LemonCard className="p-4 h-full" hoverEffect={false}>
                    <CardHeader icon={<IconPencil />} title="Behavior" />
                    <div className="flex flex-col gap-3">
                        <BehaviorCardContent scanner={scanner} />
                    </div>
                </LemonCard>
            </div>

            <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
                <LemonCard className="p-4" hoverEffect={false}>
                    <CardHeader icon={<IconBolt />} title="Scan conditions" />
                    <div className="flex flex-col gap-3">
                        <LabeledRow label="Session coverage">
                            {SAMPLING_MODE_OPTIONS.find((o) => o.value === scanner.sampling_mode)?.label ??
                                scanner.sampling_mode}
                        </LabeledRow>
                        <LabeledRow label="Sampling">{samplingPercent}%</LabeledRow>
                        <LabeledRow label="Recording filters">
                            <RecordingFilters query={scanner.query} />
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
                        <LabeledRow label="Estimated monthly cost">
                            {scanner.estimated_monthly_credits != null ? (
                                <span className="tabular-nums">
                                    {formatCreditsMaybeUsd(scanner.estimated_monthly_credits, showUsd)}{' '}
                                    <span className="text-muted">
                                        · {(scanner.estimated_monthly_observations ?? 0).toLocaleString()} observations
                                    </span>
                                </span>
                            ) : (
                                <span className="text-muted">—</span>
                            )}
                        </LabeledRow>
                        <LabeledRow label="Total observations">
                            <span className="tabular-nums">{observationStats.total.toLocaleString()}</span>
                        </LabeledRow>
                        <LabeledRow label="Outcomes">
                            <span className="text-sm">
                                {observationStats.succeeded.toLocaleString()} succeeded ·{' '}
                                {observationStats.failed.toLocaleString()} failed ·{' '}
                                {observationStats.ineligible.toLocaleString()} ineligible
                            </span>
                        </LabeledRow>
                        <div className="text-xs text-muted">
                            <CreditPriceNote dataAttr="vision-pricing-link-scanner-usage" />
                        </div>
                    </div>
                </LemonCard>
            </div>
            <ConfigVersionHistory scanner={scanner} />
        </div>
    )
}
