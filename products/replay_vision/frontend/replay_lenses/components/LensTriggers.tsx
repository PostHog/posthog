import { useActions, useValues } from 'kea'

import { LemonInput } from '@posthog/lemon-ui'

import { PropertyFilters } from 'lib/components/PropertyFilters/PropertyFilters'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { LemonSlider } from 'lib/lemon-ui/LemonSlider'

import { NodeKind } from '~/queries/schema/schema-general'
import { AnyPropertyFilter } from '~/types'

import { replayLensLogic } from '../replayLensLogic'

const RECORDING_FILTER_TYPES: TaxonomicFilterGroupType[] = [
    TaxonomicFilterGroupType.PersonProperties,
    TaxonomicFilterGroupType.SessionProperties,
    TaxonomicFilterGroupType.Cohorts,
    TaxonomicFilterGroupType.Events,
]

export function LensTriggers(): JSX.Element {
    const { lens } = useValues(replayLensLogic)
    const { setSamplingRate, setQuery } = useActions(replayLensLogic)

    if (!lens) {
        return <div className="text-muted">Loading…</div>
    }

    const samplingPercent = Math.round(lens.sampling_rate * 1000) / 10
    const properties = lens.query?.properties ?? []

    const updateProperties = (next: AnyPropertyFilter[]): void => {
        setQuery({
            kind: NodeKind.RecordingsQuery,
            ...lens.query,
            properties: next,
        })
    }

    return (
        <div className="space-y-6 max-w-3xl">
            <div className="text-sm text-muted">
                This lens runs against completed session recordings that match the filters below. Sampling controls what
                fraction of matching sessions are observed.
            </div>

            <div className="space-y-2">
                <label className="block text-sm font-medium">
                    Sampling <span className="text-danger">*</span>
                </label>
                <div className="flex items-center gap-4 max-w-md">
                    <div className="flex-1">
                        <LemonSlider
                            value={samplingPercent}
                            onChange={(value) => setSamplingRate(value / 100)}
                            min={0.1}
                            max={100}
                            step={0.1}
                        />
                    </div>
                    <div className="w-24">
                        <LemonInput
                            type="number"
                            value={samplingPercent}
                            onChange={(value) => setSamplingRate(Math.max(0, Math.min(100, Number(value) || 0)) / 100)}
                            min={0.1}
                            max={100}
                            step={0.1}
                            suffix={<span>%</span>}
                            status={samplingPercent === 0 ? 'danger' : undefined}
                        />
                    </div>
                </div>
                <div className="text-xs text-muted">
                    Each observation counts against your monthly Vision quota. A lens that matches 1,000 sessions per
                    day at 10% sampling produces ~100 observations per day.
                </div>
            </div>

            <div className="space-y-2">
                <label className="block text-sm font-medium">Recording filters</label>
                <div className="text-sm text-muted">
                    Filter by person, session, cohort, or event properties to target specific recordings. Leave empty to
                    apply this lens to all completed recordings.
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
        </div>
    )
}
