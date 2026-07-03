import { useActions, useValues } from 'kea'

import { LemonCard, LemonInput, LemonSegmentedButton, LemonSelect, LemonSnack } from '@posthog/lemon-ui'

import { resolveCategoryDropdownVariant, TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { TaxonomicPopover } from 'lib/components/TaxonomicPopover/TaxonomicPopover'
import { TestAccountFilterSwitch } from 'lib/components/TestAccountFiltersSwitch'
import UniversalFilters from 'lib/components/UniversalFilters/UniversalFilters'
import { universalFiltersLogic } from 'lib/components/UniversalFilters/universalFiltersLogic'
import { isUniversalGroupFilterLike } from 'lib/components/UniversalFilters/utils'
import { FEATURE_FLAGS } from 'lib/constants'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { LemonLabel } from 'lib/lemon-ui/LemonLabel'
import { LemonSlider } from 'lib/lemon-ui/LemonSlider'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { DurationFilter } from 'scenes/session-recordings/filters/DurationFilter'
import {
    convertUniversalFiltersToRecordingsQuery,
    deriveOperand,
    recordingsQueryToUniversalFilters,
} from 'scenes/session-recordings/filters/recordingsQueryConversions'
import { RecordingsUniversalFilterAddFilterPopover } from 'scenes/session-recordings/filters/RecordingsUniversalFiltersEmbed'
import { defaultRecordingDurationFilter } from 'scenes/session-recordings/playlist/sessionRecordingsPlaylistLogic'

import { AndOrFilterSelect } from '~/queries/nodes/InsightViz/PropertyGroupFilters/AndOrFilterSelect'
import { RecordingsQuery } from '~/queries/schema/schema-general'
import { DurationType, RecordingDurationFilter, RecordingUniversalFilters, UniversalFiltersGroup } from '~/types'

import { replayScannerLogic } from '../replayScannerLogic'
import { MOMENT_WINDOW_OPTIONS, MomentsConfig } from '../types'
import { ScannerQuotaForecast } from './ScannerQuotaForecast'

// Mirrors the recordings list taxonomy, including suggested filters so the search bar surfaces them.
const SCANNER_FILTER_TYPES: TaxonomicFilterGroupType[] = [
    TaxonomicFilterGroupType.SuggestedFilters,
    TaxonomicFilterGroupType.Replay,
    TaxonomicFilterGroupType.Events,
    TaxonomicFilterGroupType.EventProperties,
    TaxonomicFilterGroupType.Actions,
    TaxonomicFilterGroupType.Cohorts,
    TaxonomicFilterGroupType.EventFeatureFlags,
    TaxonomicFilterGroupType.PersonProperties,
    TaxonomicFilterGroupType.SessionProperties,
]

// Vision only analyzes recordings within these server-enforced duration bounds (see backend constants.py).
const DURATION_BOUNDS: Partial<Record<DurationType, { min?: number; max?: number }>> = {
    duration: { min: 15 },
    active_seconds: { min: 10, max: 3600 },
}

function clampDurationFilter(filter: RecordingDurationFilter): RecordingDurationFilter {
    const bounds = DURATION_BOUNDS[filter.key]
    if (!bounds) {
        return filter
    }
    let value = Number(filter.value) || 0
    if (bounds.min != null) {
        value = Math.max(value, bounds.min)
    }
    if (bounds.max != null) {
        value = Math.min(value, bounds.max)
    }
    return value === filter.value ? filter : { ...filter, value }
}

// Renders the bound universal-filter group's values; adding is handled by the search bar above, not an inline button.
function ScannerFilterGroup(): JSX.Element {
    const { filterGroup } = useValues(universalFiltersLogic)
    const { replaceGroupValue, removeGroupValue } = useActions(universalFiltersLogic)

    return (
        <div className="flex flex-wrap items-center gap-2">
            {filterGroup.values.map((filterOrGroup, index) =>
                isUniversalGroupFilterLike(filterOrGroup) ? (
                    <UniversalFilters.Group key={index} index={index} group={filterOrGroup}>
                        <ScannerFilterGroup />
                    </UniversalFilters.Group>
                ) : (
                    <UniversalFilters.Value
                        key={index}
                        index={index}
                        filter={filterOrGroup}
                        onRemove={() => removeGroupValue(index)}
                        onChange={(value) => replaceGroupValue(index, value)}
                    />
                )
            )}
        </div>
    )
}

const EMPTY_MOMENTS_CONFIG: MomentsConfig = { events: [], before_seconds: 60, after_seconds: 60 }

// At most 5 moments per session; overlapping windows are merged (mirrors backend moments.py constants).
const MAX_MOMENT_EVENTS = 10

function ScannerScanScope({ isNew }: { isNew: boolean }): JSX.Element {
    return (
        <LemonField name="scan_scope">
            {({ value, onChange }) => (
                <LemonCard hoverEffect={false} className="p-3 space-y-3">
                    <div className="space-y-1">
                        <LemonLabel>Scan scope</LemonLabel>
                        <div className="text-xs text-muted">
                            How much of each matching recording the scanner watches.
                            {!isNew && ' Fixed after creation.'}
                        </div>
                    </div>
                    <LemonSegmentedButton
                        value={value}
                        onChange={isNew ? onChange : () => {}}
                        size="small"
                        options={[
                            {
                                value: 'recording',
                                label: 'Entire recording',
                                disabledReason: isNew ? undefined : 'Scan scope is fixed after creation',
                            },
                            {
                                value: 'moments',
                                label: 'Moments around events',
                                disabledReason: isNew ? undefined : 'Scan scope is fixed after creation',
                            },
                        ]}
                    />
                </LemonCard>
            )}
        </LemonField>
    )
}

function ScannerMomentsConfig(): JSX.Element {
    return (
        <LemonField name="moments_config">
            {({ value, onChange }) => {
                const config = (value as MomentsConfig | null) ?? EMPTY_MOMENTS_CONFIG
                const events = config.events ?? []
                return (
                    <LemonCard hoverEffect={false} className="p-3 space-y-3">
                        <div className="space-y-1">
                            <LemonLabel>Moments</LemonLabel>
                            <div className="text-xs text-muted">
                                A short clip is scanned around each time one of these events fires.
                            </div>
                        </div>
                        <div className="flex flex-wrap items-center gap-2">
                            {events.map((momentEvent, index) => (
                                <LemonSnack
                                    key={`${momentEvent.event}-${index}`}
                                    onClose={() =>
                                        onChange({ ...config, events: events.filter((_, i) => i !== index) })
                                    }
                                >
                                    {momentEvent.event}
                                </LemonSnack>
                            ))}
                            {events.length < MAX_MOMENT_EVENTS && (
                                <TaxonomicPopover
                                    groupType={TaxonomicFilterGroupType.Events}
                                    value={null}
                                    onChange={(eventName) => {
                                        const name = String(eventName ?? '')
                                        if (!name || events.some((e) => e.event === name)) {
                                            return
                                        }
                                        onChange({ ...config, events: [...events, { event: name, properties: [] }] })
                                    }}
                                    placeholder={events.length ? 'Add another event' : 'Choose an event'}
                                    size="small"
                                    type="secondary"
                                />
                            )}
                        </div>
                        <div className="flex flex-wrap items-center gap-2 text-sm">
                            <span>Include</span>
                            <LemonSelect
                                size="small"
                                value={config.before_seconds ?? 60}
                                onChange={(v) => onChange({ ...config, before_seconds: v })}
                                options={MOMENT_WINDOW_OPTIONS}
                            />
                            <span>before and</span>
                            <LemonSelect
                                size="small"
                                value={config.after_seconds ?? 60}
                                onChange={(v) => onChange({ ...config, after_seconds: v })}
                                options={MOMENT_WINDOW_OPTIONS}
                            />
                            <span>after each event.</span>
                        </div>
                        <div className="text-xs text-muted">
                            Overlapping windows are merged into one clip; at most 5 moments are scanned per session.
                        </div>
                    </LemonCard>
                )
            }}
        </LemonField>
    )
}

export function ScannerTriggers({ scannerId }: { scannerId: string }): JSX.Element {
    const { scanner } = useValues(replayScannerLogic({ id: scannerId }))
    const { featureFlags } = useValues(featureFlagLogic)
    const categoryDropdownVariant = resolveCategoryDropdownVariant(
        featureFlags[FEATURE_FLAGS.TAXONOMIC_FILTER_CATEGORY_DROPDOWN]
    )

    if (!scanner) {
        return <div className="text-muted">Loading…</div>
    }

    const isNew = scannerId === 'new'
    const isMoments = scanner.scan_scope === 'moments'
    // Scope stays visible on existing moments scanners even if the flag is later turned off.
    const showScanScope = Boolean(featureFlags[FEATURE_FLAGS.REPLAY_VISION_MOMENTS]) || isMoments

    return (
        <div className="space-y-6">
            {showScanScope && <ScannerScanScope isNew={isNew} />}
            {isMoments && <ScannerMomentsConfig />}
            <LemonField name="sampling_rate">
                {({ value, onChange }) => {
                    const ratio = typeof value === 'number' ? value : 0
                    const samplingPercent = Math.round(ratio * 1000) / 10
                    return (
                        <LemonCard hoverEffect={false} className="p-3 space-y-3">
                            <div className="space-y-1">
                                <LemonLabel>Sampling</LemonLabel>
                                <div className="text-xs text-muted">
                                    Each observation counts against your monthly Vision quota.
                                </div>
                            </div>
                            <div className="flex items-center gap-4">
                                <div className="flex-1">
                                    <LemonSlider
                                        value={samplingPercent}
                                        onChange={(v) => onChange(v / 100)}
                                        min={0.1}
                                        max={100}
                                        step={0.1}
                                    />
                                </div>
                                <div className="w-24">
                                    <LemonInput
                                        type="number"
                                        value={samplingPercent}
                                        onChange={(v) => onChange(Math.min(100, Number(v) || 0) / 100)}
                                        min={0.1}
                                        max={100}
                                        step={0.1}
                                        suffix={<span>%</span>}
                                        status={samplingPercent < 0.1 ? 'danger' : undefined}
                                    />
                                </div>
                            </div>
                        </LemonCard>
                    )
                }}
            </LemonField>

            <LemonField name="query">
                {({ value, onChange }) => {
                    const query = value as RecordingsQuery | null
                    const universal = recordingsQueryToUniversalFilters(query)
                    const applyUniversal = (next: RecordingUniversalFilters): void => {
                        const converted = convertUniversalFiltersToRecordingsQuery(next)
                        // Overlay only the dimensions this editor renders so other query fields survive an edit.
                        onChange({
                            ...query,
                            kind: converted.kind,
                            events: converted.events,
                            actions: converted.actions,
                            properties: converted.properties,
                            console_log_filters: converted.console_log_filters,
                            having_predicates: converted.having_predicates,
                            comment_text: converted.comment_text,
                            filter_test_accounts: converted.filter_test_accounts,
                            operand: converted.operand,
                        })
                    }
                    const durationFilter = clampDurationFilter(universal.duration[0] ?? defaultRecordingDurationFilter)
                    return (
                        <LemonCard hoverEffect={false} className="p-3 space-y-3">
                            <div className="flex items-start justify-between gap-2">
                                <div className="space-y-1">
                                    <LemonLabel>
                                        {isMoments ? 'Only in sessions matching…' : 'Recording filters'}
                                    </LemonLabel>
                                    <div className="text-xs text-muted">
                                        {isMoments
                                            ? 'Moments are only scanned in sessions matching these filters. Leave empty to consider all completed recordings.'
                                            : 'Filter by event, action, person, session, or cohort. Leave empty to scan all completed recordings.'}
                                    </div>
                                </div>
                                <TestAccountFilterSwitch
                                    size="xsmall"
                                    checked={universal.filter_test_accounts ?? false}
                                    onChange={(checked) =>
                                        applyUniversal({ ...universal, filter_test_accounts: checked })
                                    }
                                />
                            </div>
                            {/* -ml-2 cancels AndOrFilterSelect's built-in prefix indent so "Match" left-aligns with the rest. */}
                            <div className="-ml-2">
                                <AndOrFilterSelect
                                    value={deriveOperand(universal.filter_group)}
                                    onChange={(type) => {
                                        if (type === deriveOperand(universal.filter_group)) {
                                            return
                                        }
                                        let values = universal.filter_group.values
                                        // With a single nested group, the effective operand lives on that child.
                                        if (values.length === 1) {
                                            const group = values[0] as UniversalFiltersGroup
                                            values = [{ ...group, type }]
                                        }
                                        applyUniversal({ ...universal, filter_group: { type, values } })
                                    }}
                                    topLevelFilter
                                    suffix={['filter', 'filters']}
                                    size="small"
                                />
                            </div>
                            <UniversalFilters
                                rootKey={`replay-scanner-${scanner.id}`}
                                group={universal.filter_group}
                                taxonomicGroupTypes={SCANNER_FILTER_TYPES}
                                onChange={(filterGroup) => applyUniversal({ ...universal, filter_group: filterGroup })}
                            >
                                {universal.filter_group.values.length > 0 &&
                                    isUniversalGroupFilterLike(universal.filter_group.values[0]) && (
                                        <UniversalFilters
                                            rootKey={`replay-scanner-${scanner.id}.nested`}
                                            group={universal.filter_group.values[0]}
                                            taxonomicGroupTypes={SCANNER_FILTER_TYPES}
                                            onChange={(nestedGroup) =>
                                                applyUniversal({
                                                    ...universal,
                                                    filter_group: {
                                                        ...universal.filter_group,
                                                        values: [
                                                            nestedGroup,
                                                            ...universal.filter_group.values.slice(1),
                                                        ],
                                                    },
                                                })
                                            }
                                        >
                                            <RecordingsUniversalFilterAddFilterPopover
                                                categoryDropdownVariant={categoryDropdownVariant}
                                                taxonomicGroupTypes={SCANNER_FILTER_TYPES}
                                            />
                                        </UniversalFilters>
                                    )}
                                <ScannerFilterGroup />
                                <div className="flex flex-wrap items-center gap-2">
                                    <span className="font-medium">Duration</span>
                                    <DurationFilter
                                        recordingDurationFilter={durationFilter}
                                        durationTypeFilter={durationFilter.key}
                                        pageKey={`replay-scanner-${scanner.id}`}
                                        size="small"
                                        onChange={(recordingDurationFilter, durationType) =>
                                            applyUniversal({
                                                ...universal,
                                                duration: [
                                                    clampDurationFilter({
                                                        ...recordingDurationFilter,
                                                        key: durationType,
                                                    }),
                                                ],
                                            })
                                        }
                                    />
                                </div>
                            </UniversalFilters>
                        </LemonCard>
                    )
                }}
            </LemonField>

            <ScannerQuotaForecast scannerId={scannerId} />
        </div>
    )
}
