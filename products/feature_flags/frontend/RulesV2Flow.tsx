import clsx from 'clsx'
import { useActions, useValues } from 'kea'

import { IconCornerDownRight, IconFlask, IconPieChart, IconTarget } from '@posthog/icons'
import { LemonBanner, LemonButton, LemonTag, Tooltip } from '@posthog/lemon-ui'

import { getSeriesColor } from 'lib/colors'
import { useDebouncedValue } from 'lib/hooks/useDebouncedValue'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { humanFriendlyNumber } from 'lib/utils/numbers'
import { capitalizeFirstLetter } from 'lib/utils/strings'
import { MatchingActorsLink } from 'scenes/feature-flags/MatchingActorsLink'

import { AnyPropertyFilter, FeatureFlagRulesV2DraftRule, FeatureFlagRulesV2Variant, JsonType } from '~/types'

import { formatPercentage } from './FractionalRolloutWarning'
import { canCountRulesV2Matches, rulesV2MatchCountLogic } from './rulesV2MatchCountLogic'

export type RulesV2RuleType = FeatureFlagRulesV2DraftRule['rule_type']

export const RULES_V2_RULE_TYPES: RulesV2RuleType[] = ['targeted_release', 'percentage_rollout', 'experiment']

export const RULES_V2_RULE_TYPE_META: Record<
    RulesV2RuleType,
    { label: string; description: string; icon: JSX.Element }
> = {
    targeted_release: {
        label: 'Targeted release',
        description: 'Serve one value to every user who matches.',
        icon: <IconTarget />,
    },
    percentage_rollout: {
        label: 'Percentage rollout',
        description: 'Serve one value to a share of the users who match.',
        icon: <IconPieChart />,
    },
    experiment: {
        label: 'Experiment',
        description: 'Split the users who match between variants.',
        icon: <IconFlask />,
    },
}

/** A value a flag can serve, styled by kind so true, false and strings read apart at a glance. */
export function RulesV2Value({ value, className }: { value: JsonType | null; className?: string }): JSX.Element {
    if (value === null) {
        return (
            <Tooltip title="The flag returns no value, so the SDK uses the fallback passed in code.">
                <span className={clsx('italic text-secondary whitespace-nowrap', className)}>no value</span>
            </Tooltip>
        )
    }
    if (typeof value === 'boolean') {
        return (
            <LemonTag type={value ? 'success' : 'muted'} className={clsx('font-mono', className)}>
                {String(value)}
            </LemonTag>
        )
    }
    return (
        <LemonTag type="default" className={clsx('font-mono max-w-full', className)} title={JSON.stringify(value)}>
            <span className="truncate">{typeof value === 'string' ? value : JSON.stringify(value)}</span>
        </LemonTag>
    )
}

/** A stored document can hold a rule type this page does not know, such as one from an older pilot. */
export function rulesV2RuleTypeMeta(ruleType: string): { label: string; description: string; icon: JSX.Element } {
    return (
        RULES_V2_RULE_TYPE_META[ruleType as RulesV2RuleType] ?? {
            label: ruleType,
            description: 'A rule type this page cannot show.',
            icon: <IconTarget />,
        }
    )
}

export function RulesV2RuleTypeLabel({ ruleType }: { ruleType: RulesV2RuleType }): JSX.Element {
    const meta = rulesV2RuleTypeMeta(ruleType)
    return (
        <span className="inline-flex items-center gap-1 font-semibold whitespace-nowrap">
            <span className="text-base text-secondary flex">{meta.icon}</span>
            {meta.label}
        </span>
    )
}

export function RulesV2RuleNumber({ index, muted }: { index: number; muted?: boolean }): JSX.Element {
    return (
        <span
            className={clsx(
                'inline-flex items-center justify-center shrink-0 size-6 rounded-full text-xs font-semibold tabular-nums border',
                muted ? 'text-muted bg-surface-secondary' : 'bg-surface-secondary'
            )}
        >
            <span className="sr-only">Rule </span>
            {index + 1}
        </span>
    )
}

/** One labelled line of a rule card. The labels line up into a column, so a card reads as "if … serve …". */
export function RulesV2RuleRow({
    label,
    children,
    aside,
    className,
}: {
    label: string
    children: React.ReactNode
    aside?: React.ReactNode
    className?: string
}): JSX.Element {
    return (
        <div className={clsx('grid grid-cols-[4.5rem_minmax(0,1fr)] gap-x-3 items-start', className)}>
            <span className="text-xxs font-semibold uppercase tracking-wide text-muted leading-7">{label}</span>
            <div className="flex flex-wrap items-start justify-between gap-x-4 gap-y-1 min-h-7">
                <div className="flex flex-col gap-1 min-w-0 flex-1">{children}</div>
                {aside && <div className="shrink-0 text-xs text-secondary leading-7">{aside}</div>}
            </div>
        </div>
    )
}

/** The line between two steps of the flow: a user who is not claimed by the step above moves on to the next one. */
export function RulesV2Connector(): JSX.Element {
    return (
        <div className="flex h-4 pl-[1.4rem]" aria-hidden>
            <div className="w-px h-full bg-border-primary" />
        </div>
    )
}

export interface RulesV2AllocationSegment {
    key: string
    label: string
    percentage: number
    color?: string
    /** Hatched, for users who leave the rule with the default value. */
    hatched?: boolean
}

const HATCHED = 'repeating-linear-gradient(135deg, var(--color-text-tertiary) 0 1.5px, transparent 1.5px 5px)'

/** Where the users a rule matches end up, as one bar. Segments are percentages of those users and total at most 100. */
export function RulesV2AllocationBar({
    segments,
    className,
}: {
    segments: RulesV2AllocationSegment[]
    className?: string
}): JSX.Element {
    const total = segments.reduce((sum, segment) => sum + segment.percentage, 0)
    return (
        <div
            className={clsx('flex h-2 w-full rounded-full overflow-hidden bg-fill-secondary', className)}
            role="img"
            aria-label={segments
                .map((segment) => `${segment.label} ${formatPercentage(segment.percentage)}`)
                .join(', ')}
        >
            {segments
                .filter((segment) => segment.percentage > 0)
                .map((segment) => (
                    <Tooltip key={segment.key} title={`${segment.label}: ${formatPercentage(segment.percentage)}`}>
                        <div
                            className="h-full first:rounded-l-full transition-[width] duration-200 ease-out border-r border-surface-primary last:border-r-0"
                            // eslint-disable-next-line react/forbid-dom-props
                            style={{
                                width: `${(segment.percentage / Math.max(total, 100)) * 100}%`,
                                background: segment.hatched ? HATCHED : (segment.color ?? 'var(--color-accent)'),
                            }}
                        />
                    </Tooltip>
                ))}
        </div>
    )
}

export function rulesV2VariantColor(index: number): string {
    return getSeriesColor(index)
}

/** Each variant's share of the rule's matching users, after the holdout and the rollout. */
export function rulesV2ExperimentSegments(rule: {
    rollout_percentage: number
    variants: FeatureFlagRulesV2Variant[]
    holdout?: { exclusion_percentage: number }
}): RulesV2AllocationSegment[] {
    const heldOut = rule.holdout?.exclusion_percentage ?? 0
    const enrolled = ((100 - heldOut) * rule.rollout_percentage) / 100
    return [
        ...(heldOut > 0 ? [{ key: 'holdout', label: 'Holdout', percentage: heldOut, hatched: true }] : []),
        ...rule.variants.map((variant, index) => ({
            key: `variant-${index}`,
            label: variant.key || `Variant ${index + 1}`,
            percentage: (enrolled * variant.weight) / 100,
            color: rulesV2VariantColor(index),
        })),
    ]
}

export function rulesV2RolloutMissText(onRolloutMiss: 'continue' | 'return_default'): string {
    return onRolloutMiss === 'continue' ? 'continue to the next rule' : 'get the default value'
}

/** The targeting count for a rule: a debounced estimate that ignores incomplete conditions. */
export function useRulesV2MatchCount(properties: AnyPropertyFilter[]): {
    countable: boolean
    affected: number | null
    total: number | null
    failed: boolean
    retry: () => void
} {
    const propertiesKey = useDebouncedValue(JSON.stringify(properties), 400)
    const countable = canCountRulesV2Matches(JSON.parse(propertiesKey))
    const logic = rulesV2MatchCountLogic({ propertiesKey })
    const { matchCount, matchCountFailed } = useValues(logic)
    const { loadMatchCount } = useActions(logic)
    return {
        countable,
        affected: matchCount?.affected ?? null,
        total: matchCount?.total ?? null,
        failed: matchCountFailed,
        retry: loadMatchCount,
    }
}

export function RulesV2MatchCountText({
    count,
    properties,
    subjects,
    rolloutPercentage,
}: {
    count: ReturnType<typeof useRulesV2MatchCount>
    properties: AnyPropertyFilter[]
    subjects: { singular: string; plural: string }
    /** Shows the share the rollout reaches instead of the targeting match. */
    rolloutPercentage?: number
}): JSX.Element | null {
    if (!count.countable) {
        return null
    }
    if (count.failed) {
        return (
            <span className="inline-flex items-center gap-1">
                Couldn't estimate
                <LemonButton size="xsmall" type="tertiary" onClick={count.retry}>
                    Retry
                </LemonButton>
            </span>
        )
    }
    if (count.affected === null) {
        return <span className="text-muted">Estimating…</span>
    }
    const reached =
        rolloutPercentage === undefined ? count.affected : Math.floor((count.affected * rolloutPercentage) / 100)
    const noun = reached === 1 ? subjects.singular : subjects.plural
    if (rolloutPercentage !== undefined) {
        return (
            <span className="tabular-nums">
                ≈ {humanFriendlyNumber(reached)} {noun}
            </span>
        )
    }
    return (
        <Tooltip
            title={
                <div className="flex flex-col gap-1">
                    <span>
                        About {humanFriendlyNumber(reached)} of {humanFriendlyNumber(count.total ?? 0)}{' '}
                        {subjects.plural} match these conditions. Earlier rules may claim some of them first.
                    </span>
                    <MatchingActorsLink
                        properties={properties}
                        resolvedGroupTypeIndex={null}
                        targetName={subjects.plural}
                    />
                </div>
            }
            interactive
        >
            <span
                // Focusable, so a keyboard user can reach the link to the matching users.
                tabIndex={0}
                className="tabular-nums underline decoration-dotted underline-offset-2 cursor-help"
            >
                ≈ {humanFriendlyNumber(reached)} {noun}
            </span>
        </Tooltip>
    )
}

/** The last step of every flow: what users get when no rule claims them. */
export function RulesV2DefaultStep({
    children,
    subjects,
    hasRules,
    catchAllRule = null,
}: {
    children: React.ReactNode
    subjects: { singular: string; plural: string }
    hasRules: boolean
    /** A rule that claims every user, so nobody falls through to this step. */
    catchAllRule?: number | null
}): JSX.Element {
    return (
        <div
            className="rounded border border-dashed bg-surface-secondary px-3 py-2.5 flex flex-wrap items-center gap-x-3 gap-y-2"
            data-attr="rules-v2-default-step"
        >
            <span className="inline-flex items-center justify-center shrink-0 size-6 rounded-full text-secondary">
                <IconCornerDownRight className="text-base" />
            </span>
            <div className="flex flex-col min-w-0 flex-1">
                <span className="font-semibold">
                    {hasRules ? `All other ${subjects.plural}` : `All ${subjects.plural}`}
                </span>
                <span className="text-xs text-secondary">
                    {catchAllRule !== null
                        ? `Rule ${catchAllRule + 1} decides the value for every ${subjects.singular}, so nobody reaches this step. Holdouts, paused experiments and rollouts that send the rest to the default still serve this value.`
                        : hasRules
                          ? `${capitalizeFirstLetter(subjects.plural)} that no rule serves get the default value.`
                          : `With no rules, all ${subjects.plural} get the default value.`}
                </span>
            </div>
            <div className="flex items-center gap-2">
                <span className="text-xxs font-semibold uppercase tracking-wide text-muted">Default</span>
                {children}
            </div>
        </div>
    )
}

/** A field error under an input that has no field of its own, rendered only while there is an error. */
export function RulesV2FieldError({ error }: { error: string | null | undefined }): JSX.Element | null {
    return error ? <LemonField.Error error={error} /> : null
}

/** Shown in a rule that an earlier rule makes unreachable. */
export function RulesV2ShadowedWarning({
    shadowedBy,
    subjects,
}: {
    shadowedBy: number | null
    /** Singular, as in "every user". */
    subjects: string
}): JSX.Element | null {
    if (shadowedBy === null) {
        return null
    }
    return (
        <div data-attr="rules-v2-rule-unreachable">
            <LemonBanner type="warning" className="text-sm">
                This rule is never reached: rule {shadowedBy + 1} already decides the value for every {subjects} this
                rule matches. Move this rule above rule {shadowedBy + 1}, or narrow rule {shadowedBy + 1}'s conditions.
            </LemonBanner>
        </div>
    )
}
