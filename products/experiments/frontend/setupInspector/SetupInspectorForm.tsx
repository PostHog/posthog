import { useActions, useValues } from 'kea'

import { CodeSnippet, Language } from 'lib/components/CodeSnippet'
import { PropertyFilters } from 'lib/components/PropertyFilters/PropertyFilters'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { TaxonomicStringPopover } from 'lib/components/TaxonomicPopover/TaxonomicPopover'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonCard } from 'lib/lemon-ui/LemonCard'
import { LemonCollapse } from 'lib/lemon-ui/LemonCollapse'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { LemonInput } from 'lib/lemon-ui/LemonInput'
import { copyToClipboard } from 'lib/utils/copyToClipboard'

import { setupInspectorLogic } from './setupInspectorLogic'

const PROPERTY_GROUP_TYPES = [TaxonomicFilterGroupType.EventProperties, TaxonomicFilterGroupType.PersonProperties]

// A cleared number input reports NaN, which would reach the request as null and fail with a 400.
function clampLimit(value: number | undefined): number {
    const limit = value !== undefined && Number.isFinite(value) ? value : 10
    return Math.min(25, Math.max(1, Math.round(limit)))
}

function InputStep({
    step,
    title,
    description,
    children,
}: {
    step: number
    title: string
    description: string
    children: React.ReactNode
}): JSX.Element {
    return (
        <LemonCard hoverEffect={false} className="p-4 flex flex-col gap-3">
            <div className="flex flex-col gap-1">
                <h4 className="mb-0">
                    {step}. {title}
                </h4>
                <p className="text-secondary text-sm mb-0">{description}</p>
            </div>
            {children}
        </LemonCard>
    )
}

export function SetupInspectorForm(): JSX.Element {
    const { inputs, toolInput, setupContext, setupContextLoading, inputsChangedSinceRead } =
        useValues(setupInspectorLogic)
    const { setInputs, loadSetupContext } = useActions(setupInspectorLogic)

    return (
        <div className="flex flex-col gap-3">
            <div className="flex flex-col gap-1">
                <h3 className="mb-0">Describe the experiment to check</h3>
                <p className="text-secondary text-sm mb-0">
                    An agent sends these inputs to experiment-setup-context before it creates an experiment. Fill them
                    in the way an agent would for the experiment you have in mind, then read the setup context. With
                    both steps empty, you get only the project-wide facts: team defaults, SDK profile, previous
                    experiments and shared metrics.
                </p>
            </div>
            <div className="grid grid-cols-1 gap-3 @min-[48rem]/drawer:grid-cols-2">
                <InputStep
                    step={1}
                    title="Where users see the change"
                    description="The event a user sends on the page or screen you change. It fills the target surface section: traffic, anonymous share and SDKs on that surface."
                >
                    <LemonField.Pure label="Event">
                        <TaxonomicStringPopover
                            groupType={TaxonomicFilterGroupType.Events}
                            value={inputs.targetEvent}
                            onChange={(targetEvent) => setInputs({ targetEvent: targetEvent || null })}
                            allowClear
                            placeholder="Pick an event, for example $pageview"
                            type="secondary"
                            size="small"
                            data-attr="experiment-setup-context-target-event"
                        />
                    </LemonField.Pure>
                    {inputs.targetEvent === '$pageview' && (
                        <LemonField.Pure label="Page URL contains" help="Matches any part of the URL, ignoring case.">
                            <LemonInput
                                size="small"
                                value={inputs.targetUrlContains}
                                onChange={(targetUrlContains) => setInputs({ targetUrlContains })}
                                placeholder="/pricing"
                            />
                        </LemonField.Pure>
                    )}
                    {inputs.targetEvent && (
                        <LemonField.Pure
                            label="Only count events where"
                            help="For example an exact $host and $pathname to isolate one page."
                        >
                            <PropertyFilters
                                pageKey="experiment-setup-context-target"
                                propertyFilters={inputs.targetProperties}
                                onChange={(targetProperties) => setInputs({ targetProperties })}
                                taxonomicGroupTypes={PROPERTY_GROUP_TYPES}
                                eventNames={[inputs.targetEvent]}
                                buttonSize="small"
                            />
                        </LemonField.Pure>
                    )}
                </InputStep>
                <InputStep
                    step={2}
                    title="What the primary metric counts"
                    description="The event the primary metric counts, such as a signup or a purchase. It fills the candidate metric section. With step 1 filled in too, it adds the conversion rate and the baseline the running time calculator takes."
                >
                    <LemonField.Pure label="Event">
                        <TaxonomicStringPopover
                            groupType={TaxonomicFilterGroupType.Events}
                            value={inputs.metricEvent}
                            onChange={(metricEvent) => setInputs({ metricEvent: metricEvent || null })}
                            allowClear
                            placeholder="Pick an event, for example a signup"
                            type="secondary"
                            size="small"
                            data-attr="experiment-setup-context-metric-event"
                        />
                    </LemonField.Pure>
                    {inputs.metricEvent && (
                        <LemonField.Pure
                            label="Only count events where"
                            help="For a metric that counts only some of these events."
                        >
                            <PropertyFilters
                                pageKey="experiment-setup-context-metric"
                                propertyFilters={inputs.metricProperties}
                                onChange={(metricProperties) => setInputs({ metricProperties })}
                                taxonomicGroupTypes={PROPERTY_GROUP_TYPES}
                                eventNames={[inputs.metricEvent]}
                                buttonSize="small"
                            />
                        </LemonField.Pure>
                    )}
                </InputStep>
            </div>
            <div className="flex flex-wrap items-center gap-2 text-sm">
                <span>List the last</span>
                <LemonInput
                    type="number"
                    size="xsmall"
                    min={1}
                    max={25}
                    className="w-16"
                    value={inputs.previousExperimentsLimit}
                    onChange={(value) => setInputs({ previousExperimentsLimit: clampLimit(value) })}
                    aria-label="Previous experiments to list"
                />
                <span>experiments and the</span>
                <LemonInput
                    type="number"
                    size="xsmall"
                    min={1}
                    max={25}
                    className="w-16"
                    value={inputs.sharedMetricsLimit}
                    onChange={(value) => setInputs({ sharedMetricsLimit: clampLimit(value) })}
                    aria-label="Shared metrics to list"
                />
                <span>most reused shared metrics.</span>
            </div>
            <div className="flex flex-wrap items-center gap-2">
                <LemonButton
                    type="primary"
                    size="small"
                    onClick={() => loadSetupContext()}
                    loading={setupContextLoading}
                    data-attr="experiment-setup-context-read"
                >
                    Read setup context
                </LemonButton>
                <LemonButton
                    type="secondary"
                    size="small"
                    onClick={() => void copyToClipboard(JSON.stringify(setupContext, null, 2), 'setup context JSON')}
                    disabledReason={setupContext ? undefined : 'Read the setup context first.'}
                    data-attr="experiment-setup-context-copy-json"
                >
                    Copy result as JSON
                </LemonButton>
                {inputsChangedSinceRead && !setupContextLoading && (
                    <span className="text-warning text-sm">
                        The inputs changed. The results below are for the previous inputs.
                    </span>
                )}
            </div>
            <LemonCollapse
                size="small"
                panels={[
                    {
                        key: 'tool-input',
                        header: 'Tool input an agent would send',
                        content: (
                            <CodeSnippet language={Language.JSON} compact>
                                {JSON.stringify(toolInput, null, 2)}
                            </CodeSnippet>
                        ),
                    },
                ]}
            />
        </div>
    )
}
