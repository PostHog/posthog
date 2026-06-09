import { useActions, useValues } from 'kea'

import { LemonDivider, LemonInput } from '@posthog/lemon-ui'

import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import UniversalFilters from 'lib/components/UniversalFilters/UniversalFilters'
import { universalFiltersLogic } from 'lib/components/UniversalFilters/universalFiltersLogic'
import { isUniversalGroupFilterLike } from 'lib/components/UniversalFilters/utils'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { LemonSlider } from 'lib/lemon-ui/LemonSlider'
import {
    convertUniversalFiltersToRecordingsQuery,
    recordingsQueryToUniversalFilters,
} from 'scenes/session-recordings/filters/recordingsQueryConversions'

import { RecordingsQuery } from '~/queries/schema/schema-general'

import { replayScannerLogic } from '../replayScannerLogic'
import { ScannerQuotaForecast } from './ScannerQuotaForecast'

// Mirrors the recordings list, minus its playlist-only groups (saved/suggested filters).
const SCANNER_FILTER_TYPES: TaxonomicFilterGroupType[] = [
    TaxonomicFilterGroupType.Replay,
    TaxonomicFilterGroupType.Events,
    TaxonomicFilterGroupType.EventProperties,
    TaxonomicFilterGroupType.Actions,
    TaxonomicFilterGroupType.Cohorts,
    TaxonomicFilterGroupType.EventFeatureFlags,
    TaxonomicFilterGroupType.PersonProperties,
    TaxonomicFilterGroupType.SessionProperties,
]

// Recursively renders the bound universal-filter group's values + the add-filter button.
function ScannerFilterGroup(): JSX.Element {
    const { filterGroup } = useValues(universalFiltersLogic)
    const { replaceGroupValue, removeGroupValue } = useActions(universalFiltersLogic)

    return (
        <div className="inline-flex flex-col gap-2">
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
            <div>
                <UniversalFilters.AddFilterButton title="Add filter" type="secondary" size="xsmall" />
            </div>
        </div>
    )
}

export function ScannerTriggers({ scannerId }: { scannerId: string }): JSX.Element {
    const { scanner } = useValues(replayScannerLogic({ id: scannerId }))

    if (!scanner) {
        return <div className="text-muted">Loading…</div>
    }

    return (
        <div className="space-y-6 max-w-3xl">
            <LemonField name="sampling_rate" label="Sampling">
                {({ value, onChange }) => {
                    const ratio = typeof value === 'number' ? value : 0
                    const samplingPercent = Math.round(ratio * 1000) / 10
                    return (
                        <div className="space-y-1">
                            <div className="flex items-center gap-4 max-w-md">
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
                                        onChange={(v) => onChange((Number(v) || 0) / 100)}
                                        min={0.1}
                                        max={100}
                                        step={0.1}
                                        suffix={<span>%</span>}
                                        status={samplingPercent === 0 ? 'danger' : undefined}
                                    />
                                </div>
                            </div>
                            <div className="text-xs text-muted">
                                Each observation counts against your monthly Vision quota.
                            </div>
                        </div>
                    )
                }}
            </LemonField>

            <LemonField name="query" label="Recording filters">
                {({ value, onChange }) => {
                    const query = value as RecordingsQuery | null
                    const universal = recordingsQueryToUniversalFilters(query)
                    return (
                        <div className="space-y-2">
                            <div className="text-sm text-muted">
                                Filter by event, action, person, session, or cohort. Leave empty to scan all completed
                                recordings.
                            </div>
                            <UniversalFilters
                                rootKey={`replay-scanner-${scanner.id}`}
                                group={universal.filter_group}
                                taxonomicGroupTypes={SCANNER_FILTER_TYPES}
                                onChange={(filterGroup) => {
                                    const next = convertUniversalFiltersToRecordingsQuery({
                                        ...universal,
                                        filter_group: filterGroup,
                                    })
                                    // Overlay only the dimensions this editor controls, so query fields it doesn't
                                    // render (e.g. session_ids, person_uuid set via API/MCP) survive an edit.
                                    onChange({
                                        ...query,
                                        kind: next.kind,
                                        events: next.events,
                                        actions: next.actions,
                                        properties: next.properties,
                                        console_log_filters: next.console_log_filters,
                                        having_predicates: next.having_predicates,
                                        comment_text: next.comment_text,
                                        filter_test_accounts: next.filter_test_accounts,
                                        operand: next.operand,
                                    })
                                }}
                            >
                                <ScannerFilterGroup />
                            </UniversalFilters>
                        </div>
                    )
                }}
            </LemonField>

            <LemonDivider className="my-0" />
            <ScannerQuotaForecast scannerId={scannerId} />
        </div>
    )
}
