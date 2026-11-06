import { useValues } from 'kea'
import { Fragment } from 'react'

import { LemonTag } from '@posthog/lemon-ui'

import 'lib/components/PropertyFilters/PropertyFilters.scss'
import { PropertyFilterButton } from 'lib/components/PropertyFilters/components/PropertyFilterButton'
import { featureFlagLogic as enabledFeaturesLogic } from 'lib/logic/featureFlagLogic'
import { rulesV2ShadowingRules } from 'scenes/feature-flags/featureFlagRulesV2Draft'

import { Noun, groupsModel } from '~/models/groupsModel'
import { FeatureFlagRulesV2Config, FeatureFlagRulesV2ExperimentRule, FeatureFlagRulesV2Rule } from '~/types'

import { isRulesV2EditableConfig } from './featureFlagConfigFormat'
import { FeatureFlagConfigReadonlyNotice } from './FeatureFlagConfigReadonlyNotice'
import { formatPercentage } from './FractionalRolloutWarning'
import {
    RulesV2AllocationBar,
    RulesV2Connector,
    RulesV2DefaultStep,
    RulesV2MatchCountText,
    RulesV2PausedRow,
    RulesV2PausedTag,
    RulesV2RuleNumber,
    RulesV2RuleRow,
    RulesV2RuleTypeLabel,
    RulesV2RulesHeading,
    RulesV2ShadowedWarning,
    RulesV2Value,
    rulesV2ExperimentSegments,
    rulesV2ReachedPercentage,
    rulesV2RolloutMissText,
    rulesV2VariantColor,
    useRulesV2MatchCount,
} from './RulesV2Flow'

function ExperimentRows({
    rule,
    subjects,
    count,
}: {
    rule: FeatureFlagRulesV2ExperimentRule
    subjects: Noun
    count: ReturnType<typeof useRulesV2MatchCount>
}): JSX.Element {
    const rolloutPercentage = rule.rollout_percentage
    const heldOut = rule.holdout?.exclusion_percentage ?? 0
    const reached = rulesV2ReachedPercentage(rule)
    return (
        <>
            {rule.holdout && (
                <RulesV2RuleRow label="Holdout">
                    <span className="leading-7">
                        Holdout excludes <b className="tabular-nums">{formatPercentage(heldOut)}</b> of matching{' '}
                        {subjects.plural}. They get the default value.
                    </span>
                </RulesV2RuleRow>
            )}
            <RulesV2RuleRow
                label="Rollout"
                aside={
                    reached === null ? null : (
                        <RulesV2MatchCountText count={count} subjects={subjects} rolloutPercentage={reached} />
                    )
                }
            >
                <span className="leading-7">
                    {rolloutPercentage >= 100 ? (
                        <>
                            Every matching {subjects.singular}
                            {rule.holdout ? ' not held out' : ''} is enrolled.
                        </>
                    ) : (
                        <>
                            <b className="tabular-nums">{formatPercentage(rolloutPercentage)}</b>
                            {rule.holdout ? ' of the rest' : ''} are enrolled. The others{' '}
                            {rulesV2RolloutMissText(rule.on_rollout_miss)}.
                        </>
                    )}
                </span>
            </RulesV2RuleRow>
            <RulesV2RuleRow label="Variants">
                <div className="flex flex-col gap-2 pt-2.5 max-w-120">
                    <RulesV2AllocationBar segments={rulesV2ExperimentSegments(rule)} />
                    <div className="flex flex-col gap-1">
                        {rule.variants.map((variant, index) => (
                            <div
                                key={variant.key}
                                className="grid grid-cols-[auto_minmax(0,12rem)_3.5rem_minmax(0,1fr)] items-center gap-x-3 text-sm"
                                data-attr="rules-v2-variant-readonly"
                            >
                                <span
                                    className="size-2.5 rounded-full"
                                    // eslint-disable-next-line react/forbid-dom-props
                                    style={{ background: rulesV2VariantColor(index) }}
                                />
                                <span className="font-mono truncate">{variant.key}</span>
                                <span className="tabular-nums text-secondary text-right">
                                    {formatPercentage(variant.weight)}
                                </span>
                                <span className="flex min-w-0">
                                    <RulesV2Value value={variant.value} />
                                </span>
                            </div>
                        ))}
                    </div>
                </div>
            </RulesV2RuleRow>
        </>
    )
}

function RuleCardReadonly({
    rule,
    index,
    config,
    subjects,
    shadowedBy,
}: {
    rule: FeatureFlagRulesV2Rule
    index: number
    config: FeatureFlagRulesV2Config
    subjects: Noun
    shadowedBy: number | null
}): JSX.Element {
    const properties = rule.targeting.properties
    const count = useRulesV2MatchCount(properties, config.aggregation_group_type_index ?? null)
    const paused = rule.rule_type === 'experiment' && rule.paused

    return (
        <div className="rounded border bg-surface-primary" data-attr="rules-v2-rule-readonly">
            <div className="flex items-center gap-2 px-3 py-2 border-b min-h-11">
                <RulesV2RuleNumber index={index} muted={shadowedBy !== null} />
                <RulesV2RuleTypeLabel ruleType={rule.rule_type} />
                {rule.description && <span className="text-secondary truncate min-w-0">{rule.description}</span>}
                <div className="flex-1" />
                {paused && <RulesV2PausedTag />}
            </div>
            <div className="px-3 py-2.5 flex flex-col gap-1.5">
                <RulesV2ShadowedWarning shadowedBy={shadowedBy} subjects={subjects} />
                <RulesV2RuleRow label="If" aside={<RulesV2MatchCountText count={count} subjects={subjects} />}>
                    {properties.length > 0 ? (
                        <div className="PropertyFilters py-0.5 flex flex-wrap items-center gap-x-1.5 gap-y-1">
                            {properties.map((property, propertyIndex) => (
                                <Fragment key={propertyIndex}>
                                    {propertyIndex > 0 && (
                                        <span className="text-xxs font-semibold uppercase text-muted">and</span>
                                    )}
                                    {/* The chip grows to fill a flex row; its own box keeps it to its content. */}
                                    <span className="flex min-w-0 max-w-full">
                                        <PropertyFilterButton item={property} compact />
                                    </span>
                                </Fragment>
                            ))}
                        </div>
                    ) : (
                        <span className="leading-7">All {subjects.plural}</span>
                    )}
                </RulesV2RuleRow>
                {paused && (
                    <RulesV2PausedRow
                        subjects={subjects}
                        defaultValue={config.default_value}
                        until="the experiment resumes"
                    />
                )}
                {rule.rule_type === 'percentage_rollout' && (
                    <RulesV2RuleRow
                        label="Rollout"
                        aside={
                            <RulesV2MatchCountText
                                count={count}
                                subjects={subjects}
                                rolloutPercentage={rule.rollout_percentage}
                            />
                        }
                    >
                        <div className="flex flex-col gap-1.5 pt-1.5">
                            <span>
                                <b className="tabular-nums">{formatPercentage(rule.rollout_percentage)}</b> of matching{' '}
                                {subjects.plural}
                                {rule.rollout_percentage < 100 && (
                                    <span className="text-secondary">
                                        {' '}
                                        · the others {rulesV2RolloutMissText(rule.on_rollout_miss)}
                                    </span>
                                )}
                            </span>
                            <RulesV2AllocationBar
                                className="max-w-80"
                                segments={[
                                    { key: 'rollout', label: 'Rolled out', percentage: rule.rollout_percentage },
                                ]}
                            />
                        </div>
                    </RulesV2RuleRow>
                )}
                {rule.rule_type === 'experiment' ? (
                    <div className={paused ? 'opacity-50 flex flex-col gap-1.5' : 'flex flex-col gap-1.5'}>
                        <ExperimentRows rule={rule} subjects={subjects} count={count} />
                    </div>
                ) : (
                    <RulesV2RuleRow label="Serve">
                        <span className="leading-7">
                            <RulesV2Value value={rule.value} />
                        </span>
                    </RulesV2RuleRow>
                )}
            </div>
        </div>
    )
}

export function FeatureFlagRulesV2Readonly({
    config,
    active = true,
    editButton,
}: {
    config: FeatureFlagRulesV2Config
    active?: boolean
    /** Shown beside the heading when the page can open the editor. */
    editButton?: JSX.Element | null
}): JSX.Element {
    const { aggregationLabel } = useValues(groupsModel)
    const { featureFlags } = useValues(enabledFeaturesLogic)
    const subjects = aggregationLabel(config.aggregation_group_type_index, true)
    const editable = isRulesV2EditableConfig(config, featureFlags)
    const shadowingRules = rulesV2ShadowingRules(config.rules)

    return (
        <div className="flex flex-col gap-3" data-attr="feature-flag-rules-v2-readonly">
            {!editable && <FeatureFlagConfigReadonlyNotice filters={config} />}
            <div className="flex flex-wrap items-start justify-between gap-2">
                <RulesV2RulesHeading subjects={subjects} />
                <div className="flex items-center gap-2">
                    <LemonTag type="default" data-attr="rules-v2-return-type">
                        Returns {config.return_type}
                    </LemonTag>
                    {editable && editButton}
                </div>
            </div>
            {!active && (
                <div className="text-xs text-secondary">
                    The flag is disabled, so these rules are not evaluated until you enable it.
                </div>
            )}
            <div className="flex flex-col">
                {config.rules.map((rule, index) => (
                    <Fragment key={rule.id ?? index}>
                        <RuleCardReadonly
                            rule={rule}
                            index={index}
                            config={config}
                            subjects={subjects}
                            shadowedBy={shadowingRules[index]}
                        />
                        <RulesV2Connector />
                    </Fragment>
                ))}
                <RulesV2DefaultStep subjects={subjects} rules={config.rules}>
                    <RulesV2Value value={config.default_value} />
                </RulesV2DefaultStep>
            </div>
        </div>
    )
}
