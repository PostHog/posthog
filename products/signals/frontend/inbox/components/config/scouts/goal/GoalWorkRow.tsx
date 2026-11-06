import { useActions, useValues } from 'kea'
import type { ReactNode } from 'react'

import { IconCode, IconDocument, IconFlask, IconPullRequest, IconToggle } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { dayjs } from 'lib/dayjs'
import { humanFriendlyNumber } from 'lib/utils/numbers'
import { urls } from 'scenes/urls'

import type { GoalScoutDetailApi, GoalScoutWorkApi } from 'products/signals/frontend/generated/api.schemas'

import { goalScoutLogic } from '../../../../logics/goal/goalScoutLogic'
import { money, pullRequestNumber, shortDate, signedPercent } from '../../../../utils/goal/format'
import { formatMde } from '../../../../utils/goal/plan'
import { effectBounds, exposedPeople, isOpen, taskFailed, taskRunning, workStatus } from '../../../../utils/goal/status'
import { GoalEffectBar } from './GoalEffectBar'
import { type GoalLink, GoalLinkList } from './GoalLinkList'
import { GoalRow } from './GoalRow'
import { GoalStat } from './GoalStat'
import { GoalTestResult } from './GoalTestResult'
import { GoalTestSteps } from './GoalTestSteps'

function ranSpan(item: GoalScoutWorkApi): { length: string; dates: string } | null {
    const start = item.exposed_at ?? item.merged_at
    if (!start || !item.finished_at) {
        return null
    }
    const days = Math.max(0, dayjs(item.finished_at).diff(dayjs(start), 'day'))
    return days
        ? {
              length: `${days} ${days === 1 ? 'day' : 'days'}`,
              dates: `${shortDate(start)} to ${shortDate(item.finished_at)}`,
          }
        : { length: 'Under a day', dates: shortDate(start) }
}

function glance(item: GoalScoutWorkApi, metric: string): ReactNode {
    const people = exposedPeople(item)
    const pr = pullRequestNumber(item.pr_url)
    const early = effectBounds(item)
    switch (item.stage) {
        case 'building':
            return item.kind === 'tracking'
                ? 'An agent checks that your app tracks the events behind the measure.'
                : 'An agent writes the change behind a feature flag.'
        case 'review':
            return `${pr ? `PR ${pr}` : 'The pull request'} is ready. ${item.kind === 'tracking' ? 'The goal starts' : 'The test starts'} when it merges.`
        case 'live':
            return [
                item.note.replace(/\.$/, '') || 'Running',
                people ? `${humanFriendlyNumber(people)} people so far` : '',
                early ? `early ${signedPercent(early[0])} to ${signedPercent(early[1])}` : 'no result yet',
            ]
                .filter(Boolean)
                .join(' · ')
        case 'stuck':
            return item.note || 'The last attempt failed.'
        default:
            if (item.kind === 'idea') {
                return <GoalTestResult item={item} metric={metric} />
            }
            return item.finished_at ? `${workStatus(item).label} ${shortDate(item.finished_at)}` : item.note
    }
}

function noteAddsInfo(item: GoalScoutWorkApi): boolean {
    const shownInGlance =
        ['building', 'review', 'live', 'stuck'].includes(item.stage) || (item.kind !== 'idea' && !item.finished_at)
    return !!item.note && !shownInGlance && item.note !== item.result.verdict
}

function workLinks(item: GoalScoutWorkApi, pullRequestTitle: string | undefined): GoalLink[] {
    const pr = pullRequestNumber(item.pr_url)
    const cleanup = item.cleanup
    const links: (GoalLink | false)[] = [
        !!item.pr_url && {
            key: 'pr',
            icon: <IconPullRequest />,
            label: `${pr ? `Pull request ${pr}` : 'Pull request'}${pullRequestTitle ? `: ${pullRequestTitle}` : ''}`,
            to: item.pr_url,
            external: true,
        },
        !!item.experiment_id && {
            key: 'experiment',
            icon: <IconFlask />,
            label: 'Experiment',
            to: urls.experiment(item.experiment_id),
        },
        !!item.report_id && {
            key: 'report',
            icon: <IconDocument />,
            label: 'Report',
            to: urls.inboxReport('reports', item.report_id),
        },
        !!cleanup?.pr_url && {
            key: 'cleanup',
            icon: <IconToggle />,
            label: [`Flag clean-up ${pullRequestNumber(cleanup.pr_url)}`.trim(), cleanup.pr_state]
                .filter(Boolean)
                .join(', '),
            to: cleanup.pr_url,
            external: true,
        },
        !!cleanup?.task_id &&
            !cleanup.pr_url && {
                key: 'cleanup-task',
                icon: <IconToggle />,
                label: taskRunning(cleanup)
                    ? 'Flag clean-up task, running'
                    : taskFailed(cleanup)
                      ? 'Flag clean-up task, failed'
                      : 'Flag clean-up task',
                to: urls.taskDetail(cleanup.task_id),
                dataAttr: 'goal-work-open-cleanup-task',
            },
        !!item.task_id && {
            key: 'task',
            icon: <IconCode />,
            label: taskRunning(item) ? 'Live task' : 'Task',
            to: urls.taskDetail(item.task_id),
            dataAttr: 'goal-work-open-task',
        },
    ]
    return links.filter((link): link is GoalLink => !!link)
}

export function GoalWorkRow({ item, goal }: { item: GoalScoutWorkApi; goal: GoalScoutDetailApi }): JSX.Element {
    const { busy, busyOperation, expandedWork, pullRequestTitles } = useValues(goalScoutLogic({ id: goal.id }))
    const { setExpandedWork, act } = useActions(goalScoutLogic({ id: goal.id }))
    const status = workStatus(item)
    const idea = item.kind === 'idea'
    const open = isOpen(item)
    const expanded = expandedWork === item.id
    const busyReason = busy ? 'Saving a change' : undefined
    const bounds = effectBounds(item)
    const showResult = idea && !open && !!item.outcome
    const early = idea && item.stage === 'live' && !!bounds
    const ran = ranSpan(item)
    const planned =
        idea && open && item.plan.days && item.plan.mde ? { days: item.plan.days, mde: item.plan.mde } : null
    const effect = (showResult || early) && bounds
    const timeline = idea && open
    const stats = (showResult && !!ran) || !!planned || item.spent_cents > 0
    const cleanupFailed = !!item.cleanup && taskFailed(item.cleanup)
    const action =
        goal.is_owner && item.stage === 'stuck' ? (
            <LemonButton
                size="small"
                type="secondary"
                loading={busyOperation === `retry:${item.id}`}
                disabledReason={busyReason}
                onClick={() => act(item.id, 'retry')}
                data-attr="goal-work-retry"
            >
                Retry
            </LemonButton>
        ) : goal.is_owner && cleanupFailed ? (
            <LemonButton
                size="small"
                type="secondary"
                loading={busyOperation === `retry_cleanup:${item.id}`}
                disabledReason={busyReason}
                onClick={() => act(item.id, 'retry_cleanup')}
                data-attr="goal-work-retry-cleanup"
            >
                Retry flag cleanup
            </LemonButton>
        ) : item.stage === 'review' && item.pr_url ? (
            <LemonButton size="small" type="secondary" to={item.pr_url} targetBlank data-attr="goal-work-review-pr">
                Review pull request
            </LemonButton>
        ) : undefined
    return (
        <GoalRow
            icon={idea ? <IconFlask className="size-4" /> : <IconCode className="size-4" />}
            title={item.title}
            tag={{ label: status.label, type: status.tag }}
            body={<span className="text-xs text-secondary">{glance(item, goal.goal_metric)}</span>}
            actions={action}
            muted={!open}
            expanded={expanded}
            onToggle={() => setExpandedWork(expanded ? null : item.id)}
            dataAttr="goal-work"
            id={`goal-work-${item.id}`}
        >
            {(effect || timeline || stats) && (
                <div className="flex flex-col gap-4 @2xl:flex-row @2xl:items-end @2xl:gap-12">
                    {effect && (
                        <GoalEffectBar
                            low={effect[0]}
                            high={effect[1]}
                            outcome={early ? '' : item.outcome}
                            metric={goal.goal_metric}
                            early={early}
                        />
                    )}
                    {timeline && !effect && (
                        <div className="w-full max-w-sm min-w-0">
                            <GoalTestSteps item={item} />
                        </div>
                    )}
                    <div className="flex shrink-0 flex-wrap gap-x-8 gap-y-2">
                        {showResult && ran && <GoalStat label={ran.dates} value={ran.length} />}
                        {planned && <GoalStat label="Test length" value={`${planned.days} days`} />}
                        {planned && <GoalStat label="Smallest change" value={`${formatMde(planned.mde)}%`} />}
                        {item.spent_cents > 0 && <GoalStat label="Spent" value={money(item.spent_cents)} />}
                    </div>
                </div>
            )}
            {timeline && effect && (
                <div className="w-full max-w-sm min-w-0">
                    <GoalTestSteps item={item} />
                </div>
            )}
            {showResult && item.result.harmed_guardrails?.length ? (
                <p className="m-0 text-xs text-danger">Harmed: {item.result.harmed_guardrails.join(', ')}</p>
            ) : null}
            {noteAddsInfo(item) && <p className="m-0 text-xs text-secondary">{item.note}</p>}
            <div className="flex flex-wrap items-center justify-between gap-4">
                <GoalLinkList links={workLinks(item, pullRequestTitles[item.pr_url])} />
                {goal.is_owner && idea && open && (
                    <LemonButton
                        size="xsmall"
                        type="tertiary"
                        status="danger"
                        className="shrink-0"
                        loading={busyOperation === `drop:${item.id}`}
                        disabledReason={busyReason}
                        onClick={() => act(item.id, 'drop')}
                        data-attr="goal-work-drop"
                    >
                        Drop idea
                    </LemonButton>
                )}
            </div>
        </GoalRow>
    )
}
