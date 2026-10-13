import { Node } from '@xyflow/react'
import { useActions, useValues } from 'kea'

import { LemonInputSelect, LemonSelect, LemonSwitch } from '@posthog/lemon-ui'

import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { TaxonomicStringPopover } from 'lib/components/TaxonomicPopover/TaxonomicPopover'
import { FEATURE_FLAGS } from 'lib/constants'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { timeZoneLabel } from 'lib/utils/timezones'
import { preflightLogic } from 'scenes/PreflightCheck/preflightLogic'

import { workflowLogic } from '../../workflowLogic'
import { HogFlowAction } from '../types'
import { HogFlowDuration } from './components/HogFlowDuration'
import { StepSchemaErrors } from './components/StepSchemaErrors'
import {
    DEFAULT_DELAY_TIMEZONE,
    DEFAULT_MAX_DELAY_DURATION,
    DelayTimezone,
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
    const { featureFlags } = useValues(featureFlagLogic)
    const { setDelayWorkflowActionConfig, setDelayMode, setDelayProperty, setDelayOffset, setDelayTimezone } =
        useActions(stepDelayLogic({ workflowLogicProps: logicProps }))

    // A step already configured for a date keeps its controls even without the flag, so the panel
    // can't quietly turn a date wait into a fixed duration.
    const dateModeAvailable = !!featureFlags[FEATURE_FLAGS.WORKFLOWS_DELAY_UNTIL_DATE] || !!config.delay_until

    const mode = getDelayMode(config)
    const expression = config.delay_until?.expression ?? ''
    const property = parseDelayExpression(expression)
    const offset = parseDelayOffset(config.delay_until?.offset)
    // An expression saved through the API can be any SQL, so it may not read back as a property pick.
    const customExpression = expression.trim() && !property ? expression : null
    const maxDelayText = getDurationText(config.max_delay_duration ?? '') ?? getDurationText(DEFAULT_MAX_DELAY_DURATION)

    if (!dateModeAvailable) {
        return (
            <>
                <StepSchemaErrors />

                <p className="mb-0">Wait for a specified duration.</p>
                <HogFlowDuration
                    value={config.delay_duration ?? ''}
                    onChange={(value) => setDelayWorkflowActionConfig(action.id, { delay_duration: value })}
                />
            </>
        )
    }

    return (
        <>
            <StepSchemaErrors />

            {/* Owns its own vertical rhythm: the panel does not space these siblings apart, so without this
                the sentence row and the inputs beneath it sit flush together. */}
            <div className="flex flex-col gap-2">
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
                                        // The offset can be any size; the wait itself is capped by max_delay_duration.
                                        allowUnbounded
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
                                // Reopen on the category the saved expression came from, so an event
                                // property does not read back as, and get silently repointed to, a person one.
                                groupType={
                                    property?.source === 'event'
                                        ? TaxonomicFilterGroupType.EventProperties
                                        : TaxonomicFilterGroupType.PersonProperties
                                }
                                groupTypes={PROPERTY_GROUP_TYPES}
                                value={property?.key}
                                placeholder="Choose a date property"
                                onChange={(key, groupType) =>
                                    setDelayProperty(action.id, {
                                        source:
                                            groupType === TaxonomicFilterGroupType.EventProperties ? 'event' : 'person',
                                        key,
                                    })
                                }
                                data-attr="workflow-delay-property"
                            />
                        </div>

                        {customExpression ? (
                            <p className="mb-0 mt-1 text-xs text-muted">
                                This step waits for <code>{customExpression}</code>, which was set through the API.
                                Choose a property to replace it.
                            </p>
                        ) : null}

                        <DelayTimezoneConfiguration
                            timezone={config.delay_until?.timezone}
                            usePersonTimezone={config.delay_until?.use_person_timezone}
                            fallbackTimezone={config.delay_until?.fallback_timezone}
                            onChange={(timezone) => setDelayTimezone(action.id, timezone)}
                        />

                        <p className="mb-0 mt-1 text-xs text-muted">
                            If the date moves further out, the wait follows it. If it moves closer, the wait still ends
                            on the original date, so the next step runs late. A run never waits more than {maxDelayText}{' '}
                            past this step.
                        </p>
                    </>
                )}
            </div>
        </>
    )
}

/**
 * A date stored without a zone ('2026-03-01', or '2026-03-01T09:00:00') is read in the zone chosen here.
 * A date that carries its own offset already names an instant and ignores this.
 */
function DelayTimezoneConfiguration({
    timezone,
    usePersonTimezone,
    fallbackTimezone,
    onChange,
}: {
    timezone?: string | null
    usePersonTimezone?: boolean
    fallbackTimezone?: string | null
    onChange: (timezone: DelayTimezone) => void
}): JSX.Element {
    const { preflight } = useValues(preflightLogic)

    const timezoneOptions = Object.entries(preflight?.available_timezones || {}).map(([tz, offset]) => ({
        key: tz,
        label: timeZoneLabel(tz, offset),
    }))

    return (
        <div className="flex flex-col gap-2">
            <LemonSwitch
                size="small"
                checked={usePersonTimezone ?? false}
                onChange={(checked) => onChange({ use_person_timezone: checked })}
                label="Use the person's timezone"
                bordered
                tooltip="Requires the GeoIP transformation to be enabled in Data pipelines → Transformations."
                data-attr="workflow-delay-use-person-timezone"
            />

            <LemonField.Pure
                label={usePersonTimezone ? 'Fallback timezone' : 'Timezone'}
                help={
                    usePersonTimezone
                        ? 'Used when the person has no timezone set.'
                        : 'A date with no timezone of its own is read in this timezone.'
                }
            >
                <LemonInputSelect
                    mode="single"
                    size="small"
                    placeholder="Select a timezone"
                    value={[(usePersonTimezone ? fallbackTimezone || timezone : timezone) || DEFAULT_DELAY_TIMEZONE]}
                    popoverClassName="z-[1000]"
                    onChange={([selected]) =>
                        onChange(usePersonTimezone ? { fallback_timezone: selected } : { timezone: selected })
                    }
                    options={timezoneOptions}
                    data-attr="workflow-delay-timezone"
                />
            </LemonField.Pure>
        </div>
    )
}
