import { useActions, useValues } from 'kea'

import { LemonBanner, LemonCard, LemonInput, LemonSegmentedButton, LemonTag } from '@posthog/lemon-ui'

import { resolveCategoryDropdownVariant, TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { TestAccountFilterSwitch } from 'lib/components/TestAccountFiltersSwitch'
import UniversalFilters from 'lib/components/UniversalFilters/UniversalFilters'
import { universalFiltersLogic } from 'lib/components/UniversalFilters/universalFiltersLogic'
import { isUniversalGroupFilterLike } from 'lib/components/UniversalFilters/utils'
import { FEATURE_FLAGS } from 'lib/constants'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { LemonLabel } from 'lib/lemon-ui/LemonLabel'
import { LemonSlider } from 'lib/lemon-ui/LemonSlider'
import { Tooltip } from 'lib/lemon-ui/Tooltip'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { DurationFilter } from 'scenes/session-recordings/filters/DurationFilter'
import {
    convertUniversalFiltersToRecordingsQuery,
    deriveOperand,
    recordingsQueryToUniversalFilters,
} from 'scenes/session-recordings/filters/recordingsQueryConversions'
import { RecordingsUniversalFilterAddFilterPopover } from 'scenes/session-recordings/filters/RecordingsUniversalFiltersEmbed'
import { defaultRecordingDurationFilter } from 'scenes/session-recordings/playlist/sessionRecordingsPlaylistLogic'

import { groupsModel } from '~/models/groupsModel'
import { AndOrFilterSelect } from '~/queries/nodes/InsightViz/PropertyGroupFilters/AndOrFilterSelect'
import { RecordingsQuery } from '~/queries/schema/schema-general'
import { PropertyFilterType, RecordingUniversalFilters, UniversalFiltersGroup } from '~/types'

import { clampDurationFilter, durationFilterError, MAX_ACTIVE_LABEL } from '../durationBounds'
import { replayScannerLogic } from '../replayScannerLogic'
import { SAMPLING_MODE_OPTIONS, SamplingMode } from '../types'
import { ScannerQuotaForecast } from './ScannerQuotaForecast'

// Mirrors the recordings list taxonomy, including suggested filters so the search bar surfaces them.
// Group properties are appended per-project from groupsModel (see scannerFilterTypes below).
const SCANNER_BASE_FILTER_TYPES: TaxonomicFilterGroupType[] = [
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

// True when any leaf in the group is an event *property* filter (type 'event'), not an event entity or person property.
// Used to surface a hint, since a key present on both the event and the person (e.g. a plan tier) matches nothing as an
// event property when it's only ever set on the person.
function groupHasEventProperty(group: UniversalFiltersGroup): boolean {
    return group.values.some((value) =>
        isUniversalGroupFilterLike(value)
            ? groupHasEventProperty(value)
            : 'type' in value && value.type === PropertyFilterType.Event
    )
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

export function ScannerTriggers({ scannerId }: { scannerId: string }): JSX.Element {
    const { scanner } = useValues(replayScannerLogic({ id: scannerId }))
    const { featureFlags } = useValues(featureFlagLogic)
    const { groupsTaxonomicTypes } = useValues(groupsModel)
    const categoryDropdownVariant = resolveCategoryDropdownVariant(
        featureFlags[FEATURE_FLAGS.TAXONOMIC_FILTER_CATEGORY_DROPDOWN]
    )
    const scannerFilterTypes = [...SCANNER_BASE_FILTER_TYPES, ...groupsTaxonomicTypes]

    if (!scanner) {
        return <div className="text-muted">Loading…</div>
    }

    return (
        <div className="space-y-6">
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
                    const durationError = durationFilterError(durationFilter)
                    return (
                        <LemonCard hoverEffect={false} className="p-3 space-y-3">
                            <div className="flex items-start justify-between gap-2">
                                <div className="space-y-1">
                                    <LemonLabel>Recording filters</LemonLabel>
                                    <div className="text-xs text-muted">
                                        Filter by event, action, person, session, or cohort. Leave empty to scan all
                                        completed recordings.
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
                            {groupHasEventProperty(universal.filter_group) && (
                                <LemonBanner type="info" dismissKey="replay-vision-event-vs-person-property-hint">
                                    <span className="text-xs">
                                        Some attributes are stored on the person, not the event. If an event property
                                        filter returns no recordings, try the same attribute under Person properties.
                                    </span>
                                </LemonBanner>
                            )}
                            <UniversalFilters
                                rootKey={`replay-scanner-${scanner.id}`}
                                group={universal.filter_group}
                                taxonomicGroupTypes={scannerFilterTypes}
                                onChange={(filterGroup) => applyUniversal({ ...universal, filter_group: filterGroup })}
                            >
                                {universal.filter_group.values.length > 0 &&
                                    isUniversalGroupFilterLike(universal.filter_group.values[0]) && (
                                        <UniversalFilters
                                            rootKey={`replay-scanner-${scanner.id}.nested`}
                                            group={universal.filter_group.values[0]}
                                            taxonomicGroupTypes={scannerFilterTypes}
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
                                                taxonomicGroupTypes={scannerFilterTypes}
                                            />
                                        </UniversalFilters>
                                    )}
                                <ScannerFilterGroup />
                                <div className="space-y-1">
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
                                        <Tooltip title="Recordings with more than 1 hour of active interaction take too long to analyze well, so Vision always skips them. This limit can't be changed.">
                                            <LemonTag type="muted" className="cursor-default">
                                                Max {MAX_ACTIVE_LABEL} active time
                                            </LemonTag>
                                        </Tooltip>
                                    </div>
                                    {durationError ? (
                                        <div className="text-danger text-xs">{durationError}</div>
                                    ) : (
                                        <div className="text-xs text-muted">
                                            Vision only scans recordings up to {MAX_ACTIVE_LABEL} of active time. Longer
                                            sessions are always skipped.
                                        </div>
                                    )}
                                </div>
                            </UniversalFilters>
                        </LemonCard>
                    )
                }}
            </LemonField>

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

            <LemonField name="sampling_mode">
                {({ value, onChange }) => {
                    const mode = (value ?? 'comprehensive') as SamplingMode
                    const option = SAMPLING_MODE_OPTIONS.find((o) => o.value === mode)
                    return (
                        <LemonCard hoverEffect={false} className="p-3 space-y-3">
                            <div className="space-y-1">
                                <LemonLabel info="Filters which matching recordings this scanner watches, based on how much activity a recording has (interactions, errors, navigation). Narrower options skip low-activity recordings so your budget goes to recordings worth watching.">
                                    Session coverage
                                </LemonLabel>
                            </div>
                            <div className="space-y-1">
                                <LemonSegmentedButton
                                    value={mode}
                                    onChange={onChange}
                                    options={SAMPLING_MODE_OPTIONS.map((o) => ({ value: o.value, label: o.label }))}
                                />
                                <div className="text-xs text-muted">{option?.description}</div>
                            </div>
                        </LemonCard>
                    )
                }}
            </LemonField>

            <ScannerQuotaForecast scannerId={scannerId} />
        </div>
    )
}
