import { useActions, useValues } from 'kea'

import {
    IconArchive,
    IconArrowRight,
    IconCheckCircle,
    IconCode,
    IconFlask,
    IconLightBulb,
    IconPause,
    IconPullRequest,
    IconTelescope,
    IconWarning,
} from '@posthog/icons'
import { LemonButton, Spinner } from '@posthog/lemon-ui'

import { cn } from 'lib/utils/css-classes'

import type { GoalScoutDetailApi } from 'products/signals/frontend/generated/api.schemas'

import { goalScoutLogic } from '../../../../logics/goal/goalScoutLogic'
import { measureValue } from '../../../../utils/goal/format'

const TILE_ICONS: Record<string, JSX.Element> = {
    ideas: <IconLightBulb />,
    edit: <IconCode />,
    idea: <IconLightBulb />,
    pull_request: <IconPullRequest />,
    experiment: <IconFlask />,
    tracking: <IconCode />,
    measure: <IconCode />,
    scout: <IconTelescope />,
    problem: <IconWarning />,
    reached: <IconCheckCircle />,
    paused: <IconPause />,
    ended: <IconArchive />,
    idle: <IconLightBulb />,
}

export function GoalStatus({ goal }: { goal: GoalScoutDetailApi }): JSX.Element {
    const { busy } = useValues(goalScoutLogic({ id: goal.id }))
    const { runStateAction } = useActions(goalScoutLogic({ id: goal.id }))
    const { state } = goal
    const action = goal.is_owner ? state.action : null
    const needsYou = !!action && state.needs_you
    const waitsForOwner = !goal.is_owner && state.needs_you
    const headline = waitsForOwner ? `Waiting for ${goal.owner_name}` : state.headline
    const detail = waitsForOwner ? `${state.headline}. ${state.detail}` : state.detail
    const target = goal.target === null ? null : measureValue(Number(goal.target), goal.unit)
    const start = goal.baseline_value === null ? null : measureValue(goal.baseline_value, goal.unit)
    return (
        <section className="flex flex-col gap-3">
            {goal.statement && (
                <div className="flex flex-col gap-1.5 rounded border border-primary bg-surface-primary px-4 py-3.5">
                    <span className="text-xs font-semibold text-secondary">Belief</span>
                    <p className="m-0 max-w-[68ch] text-[15px] leading-relaxed text-primary">{goal.statement}</p>
                </div>
            )}
            <div
                className="flex flex-wrap items-center gap-3 rounded border border-primary bg-surface-primary py-3 pr-3 pl-4"
                data-attr="goal-next-step"
            >
                <span
                    className={cn(
                        'flex shrink-0 text-lg',
                        needsYou ? 'text-warning' : state.tile === 'reached' ? 'text-success' : 'text-tertiary'
                    )}
                >
                    {state.working && !needsYou ? (
                        <Spinner className="size-4" />
                    ) : (
                        ((action && TILE_ICONS[action.kind]) ?? TILE_ICONS[state.tile] ?? <IconLightBulb />)
                    )}
                </span>
                <span className="flex min-w-0 flex-1 basis-48 flex-col gap-0.5">
                    <span className="text-sm font-semibold">{headline}</span>
                    {detail && <span className="line-clamp-2 text-xs text-secondary">{detail}</span>}
                </span>
                {action && (
                    <LemonButton
                        type={needsYou ? 'primary' : 'secondary'}
                        size="small"
                        sideIcon={<IconArrowRight />}
                        onClick={() => runStateAction(action)}
                        loading={busy}
                        data-attr="goal-next-step-action"
                    >
                        {action.label}
                    </LemonButton>
                )}
            </div>
            {goal.results?.met_at_start && (
                <p className="m-0 flex items-start gap-1.5 text-xs text-warning" data-attr="goal-results-caveat">
                    <IconWarning className="mt-0.5 size-3.5 shrink-0" />
                    <span>
                        The goal met the target before any idea shipped.{' '}
                        {start !== null && target !== null && `It started at ${start} and the target is ${target}. `}
                        The goal result does not show that the ideas worked. The experiments below do.
                    </span>
                </p>
            )}
        </section>
    )
}
