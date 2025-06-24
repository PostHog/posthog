import '@xyflow/react/dist/style.css'

import { Form } from 'kea-forms'
import { PropertyFilters } from 'lib/components/PropertyFilters/PropertyFilters'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { LemonDivider } from 'lib/lemon-ui/LemonDivider'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { LemonInput } from 'lib/lemon-ui/LemonInput'
import { LemonRadio } from 'lib/lemon-ui/LemonRadio'
import { LemonSelect } from 'lib/lemon-ui/LemonSelect'
import { ActionFilter } from 'scenes/insights/filters/ActionFilter/ActionFilter'
import { MathAvailability } from 'scenes/insights/filters/ActionFilter/ActionFilterRow/ActionFilterRow'

import { campaignLogic, CampaignLogicProps } from './campaignLogic'

export function CampaignOverview({ id }: CampaignLogicProps): JSX.Element {
    return (
        <div className="flex flex-col gap-4">
            <Form id="campaign-overview" logic={campaignLogic} props={{ id }} formKey="campaign" enableFormOnSubmit>
                <div className="flex flex-col flex-wrap gap-4 items-start mb-72">
                    <BasicInfoSection />
                    <TriggerSection />
                    <div className="flex gap-4 w-full">
                        <ConversionGoalSection />
                        <ExitConditionSection />
                    </div>
                </div>
            </Form>
        </div>
    )
}

function BasicInfoSection(): JSX.Element {
    return (
        <div className="flex flex-col gap-2 w-full rounded border bg-surface-primary p-3">
            <LemonField name="name" label="Name">
                <LemonInput />
            </LemonField>
            <LemonField name="description" label="Description">
                <LemonInput />
            </LemonField>
        </div>
    )
}

function TriggerSection(): JSX.Element {
    return (
        <div className="flex flex-col gap-2 w-full rounded border bg-surface-primary p-3">
            <div className="flex flex-col">
                <p className="text-lg font-semibold mb-1">Campaign trigger event</p>
                <p className="mb-0">Choose which events or actions will enter a user into the campaign.</p>
            </div>
            <LemonField name="triggerEvents">
                {({ value, onChange }) => (
                    <ActionFilter
                        filters={value ?? {}}
                        setFilters={onChange}
                        typeKey="campaign-trigger"
                        mathAvailability={MathAvailability.None}
                        hideRename
                        hideDuplicate
                        showNestedArrow={false}
                        actionsTaxonomicGroupTypes={[TaxonomicFilterGroupType.Events, TaxonomicFilterGroupType.Actions]}
                        propertiesTaxonomicGroupTypes={[
                            TaxonomicFilterGroupType.EventProperties,
                            TaxonomicFilterGroupType.EventFeatureFlags,
                            TaxonomicFilterGroupType.Elements,
                            TaxonomicFilterGroupType.PersonProperties,
                            TaxonomicFilterGroupType.HogQLExpression,
                        ]}
                        propertyFiltersPopover
                        addFilterDefaultOptions={{
                            id: '$pageview',
                            name: '$pageview',
                            type: 'events',
                        }}
                        buttonProps={{
                            type: 'secondary',
                        }}
                        buttonCopy="Add trigger event"
                    />
                )}
            </LemonField>
        </div>
    )
}

function ConversionGoalSection(): JSX.Element {
    return (
        <div className="flex flex-col gap-2 w-1/2 rounded border bg-surface-primary p-3 h-fit">
            <div className="flex flex-col">
                <p className="text-lg font-semibold mb-1">Conversion goal</p>
                <p className="mb-0">Define what properties a user must have to be considered converted.</p>
            </div>

            <div className="flex gap-1">
                <div className="w-2/3">
                    <LemonField name={['conversion', 'filters']} label="Conversion properties">
                        {({ value, onChange }) => (
                            <PropertyFilters
                                propertyFilters={value ?? []}
                                taxonomicGroupTypes={[
                                    TaxonomicFilterGroupType.PersonProperties,
                                    TaxonomicFilterGroupType.Cohorts,
                                    TaxonomicFilterGroupType.HogQLExpression,
                                ]}
                                onChange={onChange}
                                pageKey="campaign-conversion-properties"
                                hideBehavioralCohorts
                            />
                        )}
                    </LemonField>
                </div>
                <LemonDivider vertical />
                <div className="w-1/3">
                    <LemonField
                        name={['conversion', 'window']}
                        label="Conversion window"
                        info="How long after entering the campaign should we check for conversion? After this window, users will be considered for conversion."
                    >
                        {({ value, onChange }) => (
                            <LemonSelect
                                value={value}
                                onChange={onChange}
                                options={[
                                    { value: 24 * 60 * 60, label: '24 hours' },
                                    { value: 7 * 24 * 60 * 60, label: '7 days' },
                                    { value: 14 * 24 * 60 * 60, label: '14 days' },
                                    { value: 30 * 24 * 60 * 60, label: '30 days' },
                                ]}
                            />
                        )}
                    </LemonField>
                </div>
            </div>
        </div>
    )
}

function ExitConditionSection(): JSX.Element {
    return (
        <div className="flex flex-col gap-2 w-1/2 rounded border bg-surface-primary p-3">
            <div className="flex flex-col">
                <p className="text-lg font-semibold mb-1">Exit condition</p>
                <p className="mb-0">Choose how your users move through the campaign.</p>
            </div>

            <LemonField name="exit_condition">
                {({ value, onChange }) => (
                    <LemonRadio
                        value={value}
                        onChange={onChange}
                        options={[
                            {
                                value: 'exit_only_at_end',
                                label: 'Exit at end of workflow',
                            },
                            {
                                value: 'exit_on_trigger_not_matched',
                                label: 'Exit on trigger not matched',
                            },
                            {
                                value: 'exit_on_conversion',
                                label: 'Exit on conversion',
                            },
                            {
                                value: 'exit_on_trigger_not_matched_or_conversion',
                                label: 'Exit on trigger not matched or conversion',
                            },
                        ]}
                    />
                )}
            </LemonField>
        </div>
    )
}
