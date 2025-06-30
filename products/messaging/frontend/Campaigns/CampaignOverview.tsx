import '@xyflow/react/dist/style.css'

import { useValues } from 'kea'
import { Form } from 'kea-forms'
import posthog from 'posthog-js'

import { PropertyFilters } from 'lib/components/PropertyFilters/PropertyFilters'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { LemonDivider } from 'lib/lemon-ui/LemonDivider'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { LemonInput } from 'lib/lemon-ui/LemonInput'
import { LemonRadio } from 'lib/lemon-ui/LemonRadio'
import { LemonSelect } from 'lib/lemon-ui/LemonSelect'

import { campaignLogic, CampaignLogicProps } from './campaignLogic'
import { HogFlowFilters } from './hogflows/filters/HogFlowFilters'
import { IconBolt, IconLeave, IconPlusSmall, IconTarget } from '@posthog/icons'
import { LemonButton, LemonLabel, LemonTag, LemonTextArea, lemonToast } from '@posthog/lemon-ui'

export function CampaignOverview(props: CampaignLogicProps): JSX.Element {
    return (
        <div className="flex flex-col gap-4">
            <Form id="campaign-overview" logic={campaignLogic} props={props} formKey="campaign" enableFormOnSubmit>
                <div className="flex flex-col flex-wrap gap-4 items-start">
                    <BasicInfoSection />
                    <TriggerSection {...props} />
                    <ConversionGoalSection />
                    <ExitConditionSection />
                </div>
            </Form>
        </div>
    )
}

function BasicInfoSection(): JSX.Element {
    return (
        <div className="flex flex-col gap-2 py-2 w-120">
            <LemonField name="name" label="Name">
                <LemonInput />
            </LemonField>
            <LemonField name="description" label="Description">
                <LemonTextArea placeholder="Help your teammates understand this campaign" />
            </LemonField>
        </div>
    )
}

function TriggerSection(props: CampaignLogicProps): JSX.Element {
    const logic = campaignLogic(props)
    const { campaignValidationErrors } = useValues(logic)

    return (
        <div className="flex flex-col py-2 w-full">
            <div className="flex flex-col">
                <span className="flex items-center">
                    <IconBolt className="text-lg" />
                    <span className="text-lg font-semibold">Trigger event</span>
                </span>
                <p className="mb-0">Choose which events or actions will enter a user into the campaign.</p>
            </div>
            <LemonDivider />
            <LemonField name={['trigger', 'filters']} className="max-w-200">
                {({ value, onChange }) => (
                    <HogFlowFilters
                        filters={value ?? {}}
                        setFilters={onChange}
                        typeKey="campaign-trigger"
                        buttonCopy="Add trigger event"
                    />
                )}
            </LemonField>
            {campaignValidationErrors.trigger?.filters && (
                <span className="text-danger text-sm mt-2">{campaignValidationErrors.trigger.filters}</span>
            )}
        </div>
    )
}

function ConversionGoalSection(): JSX.Element {
    return (
        <div className="flex flex-col py-2 w-full">
            <div className="flex flex-col">
                <span className="flex items-center gap-1">
                    <IconTarget className="text-lg" />
                    <span className="text-lg font-semibold">Conversion goal (optional)</span>
                </span>
                <p className="mb-0">Define what a user must do to be considered converted.</p>
            </div>
            <LemonDivider />

            <div className="flex gap-1 max-w-240">
                <div className="flex flex-col flex-2 gap-4">
                    <LemonField name={['conversion', 'filters']} label="Detect conversion from property changes">
                        {({ value, onChange }) => (
                            <PropertyFilters
                                buttonText="Add property conversion"
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
                    <div className="flex flex-col gap-1">
                        <LemonLabel>
                            Detect conversion from events
                            <LemonTag>Coming soon</LemonTag>
                        </LemonLabel>
                        <LemonButton
                            type="secondary"
                            size="small"
                            icon={<IconPlusSmall />}
                            onClick={() => {
                                posthog.capture('messaging campaign event conversion clicked')
                                lemonToast.info('Event targeting coming soon!')
                            }}
                        >
                            Add event conversion
                        </LemonButton>
                    </div>
                </div>
                <LemonDivider vertical />
                <div className="flex-1">
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
        <div className="flex flex-col flex-1 w-full py-2">
            <div className="flex flex-col">
                <span className="flex items-center gap-1">
                    <IconLeave className="text-lg" />
                    <span className="text-lg font-semibold">Exit condition</span>
                </span>
                <p className="mb-0">Choose how your users move through the campaign.</p>
            </div>
            <LemonDivider />
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
