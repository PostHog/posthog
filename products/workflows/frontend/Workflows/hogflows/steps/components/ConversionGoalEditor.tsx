import { LemonLabel } from '@posthog/lemon-ui'

import { PropertyFilters } from 'lib/components/PropertyFilters/PropertyFilters'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'

import { HogFlowEventFilters, WORKFLOW_OPERATOR_ALLOWLIST } from '../../filters/HogFlowFilters'

// Structural shape of a workflow conversion goal, compatible with both the frontend HogFlow
// type and the generated HogFlowConversionApi type.
export interface ConversionGoalValue {
    window_minutes?: number | null
    filters?: any
    events?: { filters?: any; name?: string }[]
    bytecode?: unknown
}

export interface ConversionGoalEditorProps {
    conversion: ConversionGoalValue | null | undefined
    onChange: (conversion: ConversionGoalValue) => void
    /** Unique key for the filter pickers, so multiple editors on one page don't share state. */
    pageKey: string
}

export function ConversionGoalEditor({ conversion, onChange, pageKey }: ConversionGoalEditorProps): JSX.Element {
    const conversionEventFilters = conversion?.events?.[0]?.filters ?? {}

    return (
        <div className="flex flex-col gap-4">
            <div className="flex flex-col gap-1 items-start">
                <LemonLabel>Detect conversion from property changes</LemonLabel>
                <PropertyFilters
                    buttonText="Add property conversion"
                    buttonClassName="grow-0"
                    propertyFilters={conversion?.filters ?? []}
                    taxonomicGroupTypes={[
                        TaxonomicFilterGroupType.PersonProperties,
                        TaxonomicFilterGroupType.HogQLExpression,
                    ]}
                    onChange={(filters) => onChange({ window_minutes: null, ...conversion, filters })}
                    pageKey={`${pageKey}-properties`}
                    hideBehavioralCohorts
                    operatorAllowlist={WORKFLOW_OPERATOR_ALLOWLIST}
                    logicalRowDivider
                />
            </div>

            <div className="flex flex-col gap-1 items-start w-full">
                <LemonLabel>Detect conversion from events</LemonLabel>
                <HogFlowEventFilters
                    filtersKey={`${pageKey}-events`}
                    filters={conversionEventFilters}
                    setFilters={(newFilters) =>
                        onChange({
                            window_minutes: null,
                            filters: [],
                            ...conversion,
                            events: newFilters ? [{ filters: newFilters }] : undefined,
                        })
                    }
                    typeKey={`${pageKey}-event`}
                    buttonCopy="Add event"
                />
            </div>
        </div>
    )
}
