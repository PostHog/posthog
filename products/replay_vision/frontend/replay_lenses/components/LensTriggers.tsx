import { useValues } from 'kea'
import { Field } from 'kea-forms'

import { LemonInput } from '@posthog/lemon-ui'

import { PropertyFilters } from 'lib/components/PropertyFilters/PropertyFilters'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { LemonSlider } from 'lib/lemon-ui/LemonSlider'

import { NodeKind, RecordingsQuery } from '~/queries/schema/schema-general'
import { AnyPropertyFilter } from '~/types'

import { replayLensLogic } from '../replayLensLogic'
import { LensQuotaForecast } from './LensQuotaForecast'

const RECORDING_FILTER_TYPES: TaxonomicFilterGroupType[] = [
    TaxonomicFilterGroupType.PersonProperties,
    TaxonomicFilterGroupType.SessionProperties,
    TaxonomicFilterGroupType.Cohorts,
    TaxonomicFilterGroupType.Events,
]

export function LensTriggers({ lensId, tabId }: { lensId: string; tabId: string }): JSX.Element {
    const { lens } = useValues(replayLensLogic({ id: lensId, tabId }))

    if (!lens) {
        return <div className="text-muted">Loading…</div>
    }

    return (
        <div className="space-y-6 max-w-3xl">
            <div className="text-sm text-muted">
                This lens runs against completed session recordings that match the filters below. Sampling controls what
                fraction of matching sessions are observed.
            </div>

            <Field name="sampling_rate" label="Sampling">
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
                                Each observation counts against your monthly Vision quota. A lens that matches 1,000
                                sessions per day at 10% sampling produces ~100 observations per day.
                            </div>
                        </div>
                    )
                }}
            </Field>

            <Field name="query" label="Recording filters">
                {({ value, onChange }) => {
                    const query = value as RecordingsQuery | null
                    const properties = query?.properties ?? []
                    const updateProperties = (next: AnyPropertyFilter[]): void => {
                        onChange({
                            kind: NodeKind.RecordingsQuery,
                            ...query,
                            properties: next,
                        })
                    }
                    return (
                        <div className="space-y-2">
                            <div className="text-sm text-muted">
                                Filter by person, session, cohort, or event properties to target specific recordings.
                                Leave empty to apply this lens to all completed recordings.
                            </div>
                            <PropertyFilters
                                propertyFilters={properties}
                                onChange={updateProperties}
                                pageKey={`replay-lens-${lens.id}-properties`}
                                taxonomicGroupTypes={RECORDING_FILTER_TYPES}
                                addText="Add filter"
                                hasRowOperator={false}
                                sendAllKeyUpdates
                            />
                        </div>
                    )
                }}
            </Field>

            <LensQuotaForecast lensId={lensId} tabId={tabId} />
        </div>
    )
}
