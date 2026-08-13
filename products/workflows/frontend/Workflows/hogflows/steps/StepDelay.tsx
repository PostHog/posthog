import { Node } from '@xyflow/react'
import { useActions, useValues } from 'kea'

import { LemonSelect } from '@posthog/lemon-ui'

import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { TaxonomicStringPopover } from 'lib/components/TaxonomicPopover/TaxonomicPopover'

import { workflowLogic } from '../../workflowLogic'
import { HogFlowAction } from '../types'
import { HogFlowDuration } from './components/HogFlowDuration'
import { StepSchemaErrors } from './components/StepSchemaErrors'
import {
    DEFAULT_MAX_DELAY_DURATION,
    getDelayMode,
    getDurationText,
    parseDelayExpression,
    parseDelayOffset,
    stepDelayLogic,
} from './stepDelayLogic'

const PROPERTY_GROUP_TYPES = [TaxonomicFilterGroupType.PersonProperties, TaxonomicFilterGroupType.EventProperties]

export function StepDelayConfiguration({
    node,
}: {
    node: Node<Extract<HogFlowAction, { type: 'delay' }>>
}): JSX.Element {
    const action = node.data
    const config = action.config

    const { logicProps } = useValues(workflowLogic)
    const { setDelayWorkflowActionConfig, setDelayMode, setDelayProperty, setDelayOffset } = useActions(
        stepDelayLogic({ workflowLogicProps: logicProps })
    )

    const mode = getDelayMode(config)
    const expression = config.delay_until?.expression ?? ''
    const property = parseDelayExpression(expression)
    const offset = parseDelayOffset(config.delay_until?.offset)
    // An expression saved through the API can be any SQL, so it may not read back as a property pick.
    const customExpression = expression.trim() && !property ? expression : null
    const maxDelayText = getDurationText(config.max_delay_duration ?? '') ?? getDurationText(DEFAULT_MAX_DELAY_DURATION)

    return (
        <>
            <StepSchemaErrors />

            <div className="flex flex-wrap items-center gap-2">
                <span>Wait for</span>
                <LemonSelect
                    size="small"
                    value={mode}
                    onChange={(value) => setDelayMode(action.id, value)}
                    options={[
                        { label: 'a specified duration', value: 'duration' as const },
                        { label: 'a date on the person or event', value: 'until' as const },
                    ]}
                    data-attr="workflow-delay-mode"
                />
            </div>

            {mode === 'duration' ? (
                <HogFlowDuration
                    value={config.delay_duration ?? ''}
                    onChange={(value) => setDelayWorkflowActionConfig(action.id, { delay_duration: value })}
                />
            ) : (
                <>
                    <div className="flex flex-wrap items-center gap-2">
                        {offset.direction !== 'on' ? (
                            // Narrower than the duration mode's own input: this one is part of a sentence
                            // that has to fit next to the direction and the property.
                            <div className="w-44">
                                <HogFlowDuration
                                    value={offset.duration}
                                    onChange={(duration) => setDelayOffset(action.id, { ...offset, duration })}
                                />
                            </div>
                        ) : null}
                        <LemonSelect
                            size="small"
                            value={offset.direction}
                            onChange={(value) => setDelayOffset(action.id, { ...offset, direction: value })}
                            options={[
                                { label: 'on', value: 'on' as const },
                                { label: 'before', value: 'before' as const },
                                { label: 'after', value: 'after' as const },
                            ]}
                            data-attr="workflow-delay-offset-direction"
                        />
                        <TaxonomicStringPopover
                            size="small"
                            groupType={TaxonomicFilterGroupType.PersonProperties}
                            groupTypes={PROPERTY_GROUP_TYPES}
                            value={property?.key}
                            placeholder="Choose a date property"
                            onChange={(key, groupType) =>
                                setDelayProperty(action.id, {
                                    source: groupType === TaxonomicFilterGroupType.EventProperties ? 'event' : 'person',
                                    key,
                                })
                            }
                            data-attr="workflow-delay-property"
                        />
                    </div>

                    {customExpression ? (
                        <p className="mb-0 text-xs text-muted">
                            This step waits for <code>{customExpression}</code>, which was set through the API. Choose a
                            property to replace it.
                        </p>
                    ) : null}

                    <p className="mb-0 text-xs text-muted">
                        The property is read again each time the run wakes, so a date that moves still applies. A run
                        never waits more than {maxDelayText} past this step.
                    </p>
                </>
            )}
        </>
    )
}
