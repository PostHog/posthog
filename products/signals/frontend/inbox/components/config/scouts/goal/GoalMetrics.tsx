import type { ReactNode } from 'react'

import { LemonTag, Link } from '@posthog/lemon-ui'

import { dayjs } from 'lib/dayjs'
import { LemonProgress } from 'lib/lemon-ui/LemonProgress'
import { cn } from 'lib/utils/css-classes'
import { pluralize } from 'lib/utils/strings'
import { urls } from 'scenes/urls'

import { SceneSection } from '~/layout/scenes/components/SceneSection'
import type { InsightShortId } from '~/types'

import type { GoalScoutDetailApi, GoalScoutSpendApi } from 'products/signals/frontend/generated/api.schemas'

import {
    delta,
    difference,
    elapsed,
    latestValue,
    measureValue,
    money,
    reachedTarget,
    shortDate,
    timeLabels,
} from '../../../../utils/goal/format'
import { GoalTrendChart } from './GoalTrendChart'

interface Series {
    values: number[]
    labels: string[]
}

interface SpendFact {
    label: string
    value: string
    note?: string
}

function ChartCell({
    label,
    aside,
    value,
    note,
    chart,
    className,
}: {
    label: ReactNode
    aside?: ReactNode
    value: ReactNode
    note?: ReactNode
    chart?: ReactNode
    className?: string
}): JSX.Element {
    return (
        <div className={cn('flex min-w-0 flex-col gap-2 px-4 py-3', className)}>
            <div className="flex min-h-5 items-center justify-between gap-2">
                <span className="truncate text-xs text-tertiary">{label}</span>
                {aside}
            </div>
            <div className="flex min-w-0 flex-wrap items-baseline gap-x-2 gap-y-0.5">
                <span className="text-2xl leading-none font-semibold tabular-nums">{value}</span>
                {note && <span className="text-xs text-secondary tabular-nums">{note}</span>}
            </div>
            {chart}
        </div>
    )
}

function spendFacts(spend: GoalScoutSpendApi, ideas: number): SpendFact[] {
    const facts: SpendFact[] = []
    if (spend.scout_cents > 0) {
        facts.push({
            label: 'Finding ideas',
            value: money(spend.scout_cents),
            note: pluralize(spend.scout_runs, 'scout run'),
        })
    }
    if (spend.ideas_cents > 0) {
        facts.push({ label: 'Building and testing', value: money(spend.ideas_cents), note: pluralize(ideas, 'idea') })
    }
    if (spend.tracking_cents > 0) {
        facts.push({ label: 'Checking tracking', value: money(spend.tracking_cents) })
    }
    if (spend.per_tested_idea_cents !== null) {
        facts.push({ label: 'Per idea tested', value: money(spend.per_tested_idea_cents), note: 'search included' })
    }
    return facts
}

function measureSeries(goal: GoalScoutDetailApi, end: number | null): Series | null {
    if (goal.metric.values.length > 1) {
        return { values: goal.metric.values, labels: timeLabels(goal.metric.dates) }
    }
    if (end === null || goal.baseline_value === null || !goal.baseline_at) {
        return null
    }
    const { results } = goal
    const endLabel = results ? shortDate(results.ended_at ?? results.started_at) : 'Now'
    return { values: [goal.baseline_value, end], labels: [shortDate(goal.baseline_at), endLabel] }
}

export function GoalMetrics({ goal }: { goal: GoalScoutDetailApi }): JSX.Element {
    const { results, money: budget } = goal
    const comparison = goal.direction === 'decrease' ? '≤' : '≥'
    const target = goal.target === null ? null : Number(goal.target)
    const latest = latestValue(goal.metric)
    const value = latest?.value ?? null
    const reached = reachedTarget(value, target, goal.direction)
    const series = measureSeries(goal, results ? value : goal.metric.current)
    const ended = goal.work
        .filter((item) => item.kind === 'idea' && (item.stage === 'done' || item.stage === 'dropped'))
        .sort((a, b) => (a.number ?? 0) - (b.number ?? 0))
    const facts = results ? spendFacts(results.spend, ended.length) : []
    const budgetTotal = results ? budget.spent_cents + results.spend.returned_cents : budget.allocated_cents
    const harmed = results ? ended.filter((item) => item.result.harmed_guardrails?.length) : []
    const ideasTested = results ? ended.length : goal.ideas_tried
    const ideasWon = results ? ended.filter((item) => item.outcome === 'won').length : goal.ideas_won
    const measureLabel = goal.goal_insight ? (
        <Link to={urls.insightView(goal.goal_insight as InsightShortId)} subtle>
            {goal.goal_metric}
        </Link>
    ) : (
        goal.goal_metric
    )
    const reachedTag =
        reached === null ? null : results ? (
            <LemonTag size="small" type={reached ? 'success' : 'warning'}>
                {reached ? 'Target reached' : 'Below target'}
            </LemonTag>
        ) : (
            <LemonTag size="small" type={reached ? 'success' : 'default'}>
                {reached || value === null || target === null
                    ? 'At target'
                    : `${difference(Math.abs(target - value), goal.unit)} to go`}
            </LemonTag>
        )
    const card = (
        <div className="flex flex-col rounded border border-primary bg-surface-primary">
            <div className="grid grid-cols-1 @2xl:grid-cols-2">
                <ChartCell
                    label={measureLabel}
                    aside={reachedTag}
                    value={
                        value === null ? (
                            <span className="text-base text-secondary">{results ? 'Not recorded' : 'No data yet'}</span>
                        ) : (
                            <>
                                {measureValue(value, goal.unit)}
                                {!results && latest?.stale && latest.date && (
                                    <span className="ml-2 text-xs font-normal text-secondary">
                                        on {dayjs(latest.date).format('MMM D')}
                                    </span>
                                )}
                            </>
                        )
                    }
                    note={
                        value !== null && goal.baseline_value !== null
                            ? `${delta(goal.baseline_value, value, goal.unit)} from ${measureValue(goal.baseline_value, goal.unit)}`
                            : (!results && goal.metric.message) || undefined
                    }
                    chart={
                        series && (
                            <GoalTrendChart
                                values={series.values}
                                labels={series.labels}
                                reference={target}
                                referenceLabel={`Target ${comparison}`}
                                tone={reached ? 'success' : results && reached === false ? 'warning' : 'neutral'}
                                format={(point) => measureValue(point, goal.unit)}
                            />
                        )
                    }
                />
                <ChartCell
                    className="border-t border-primary @2xl:border-t-0 @2xl:border-l"
                    label="Spend"
                    aside={
                        <span className="text-xs text-tertiary tabular-nums">
                            {results
                                ? results.ended_at && `Took ${elapsed(results.started_at, results.ended_at)}`
                                : `${money(budget.available_cents)} left`}
                        </span>
                    }
                    value={money(budget.spent_cents)}
                    note={[
                        results ? '' : `of ${money(budget.allocated_cents)}`,
                        ideasTested
                            ? `${pluralize(ideasTested, 'idea')} tested, ${ideasWon} won`
                            : results
                              ? 'No ideas tested'
                              : 'No ideas tested yet',
                        results && results.spend.returned_cents > 0
                            ? `${money(results.spend.returned_cents)} returned`
                            : '',
                    ]
                        .filter(Boolean)
                        .join(' · ')}
                    chart={
                        results
                            ? budgetTotal > 0 && (
                                  <div className="flex flex-col gap-1.5 pt-3">
                                      <LemonProgress
                                          percent={(budget.spent_cents / budgetTotal) * 100}
                                          strokeColor="var(--color-accent)"
                                      />
                                      <span className="text-xs text-tertiary tabular-nums">
                                          {money(budget.spent_cents)} of {money(budgetTotal)} budget used
                                      </span>
                                  </div>
                              )
                            : new Set(goal.spend_history.map((point) => point.spent_cents)).size > 2 && (
                                  <GoalTrendChart
                                      values={goal.spend_history.map((point) => point.spent_cents / 100)}
                                      labels={timeLabels(goal.spend_history.map((point) => point.at))}
                                      reference={budget.allocated_cents / 100}
                                      referenceLabel="Budget"
                                      format={(point) => money(Math.round(point * 100))}
                                  />
                              )
                    }
                />
            </div>
            {goal.secondary_metrics.length > 0 && (
                <div className="flex flex-wrap items-center gap-x-4 gap-y-1 border-t border-primary px-4 py-2 text-xs">
                    <span className="font-semibold text-secondary">
                        {goal.secondary_metrics.length === 1 ? 'Guardrail' : 'Guardrails'}
                    </span>
                    {results ? (
                        <>
                            <span className="text-secondary">
                                {goal.secondary_metrics.map((metric) => metric.name).join(', ')}
                            </span>
                            {harmed.length ? (
                                <span className="text-danger">
                                    {harmed.map((idea) => `Idea ${idea.number ?? ''}`.trim()).join(', ')} harmed it and{' '}
                                    {harmed.length === 1 ? 'was' : 'were'} stopped
                                </span>
                            ) : (
                                <span className="text-success">
                                    {results.spend.tested_ideas ? 'No test harmed it' : 'Not tested'}
                                </span>
                            )}
                        </>
                    ) : (
                        goal.secondary_metrics.map((guardrail, index) => {
                            const current = goal.secondary_values[index]?.current
                            return (
                                <span
                                    key={guardrail.insight}
                                    className="flex flex-wrap items-center gap-x-1.5 text-secondary"
                                >
                                    <Link to={urls.insightView(guardrail.insight as InsightShortId)} subtle>
                                        {guardrail.name}
                                    </Link>
                                    {current !== null && current !== undefined && (
                                        <span className="font-semibold text-primary tabular-nums">
                                            {measureValue(current, goal.secondary_values[index].unit)}
                                        </span>
                                    )}
                                    <span className="text-tertiary">
                                        must not {guardrail.direction === 'decrease' ? 'rise' : 'drop'}
                                        {guardrail.max_regression
                                            ? ` more than ${measureValue(guardrail.max_regression * 100, '%')}`
                                            : ''}
                                    </span>
                                </span>
                            )
                        })
                    )}
                </div>
            )}
            {facts.length > 1 && (
                <div className="grid grid-cols-2 gap-3 border-t border-primary px-4 py-3 @2xl:grid-cols-4">
                    {facts.map((fact) => (
                        <div key={fact.label} className="flex min-w-0 flex-col gap-0.5">
                            <span className="text-xs text-tertiary">{fact.label}</span>
                            <span className="text-sm font-semibold tabular-nums">{fact.value}</span>
                            {fact.note && <span className="text-xs text-secondary">{fact.note}</span>}
                        </div>
                    ))}
                </div>
            )}
        </div>
    )
    return results ? (
        <SceneSection title="Result" titleSize="sm" className="gap-y-2">
            {card}
        </SceneSection>
    ) : (
        card
    )
}
