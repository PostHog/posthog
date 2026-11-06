import { dayjs } from 'lib/dayjs'
import { cn } from 'lib/utils/css-classes'

import type { GoalScoutWorkApi } from 'products/signals/frontend/generated/api.schemas'

import { shortDate } from '../../../../utils/goal/format'

type StepState = 'done' | 'current' | 'todo' | 'failed'

interface Step {
    label: string
    detail: string
    state: StepState
    tone?: 'success' | 'danger'
}

const DOT: Record<StepState, string> = {
    done: 'bg-success border-transparent',
    current: 'bg-accent border-accent animate-pulse motion-reduce:animate-none',
    todo: 'bg-surface-primary border-primary',
    failed: 'bg-danger border-danger',
}

function testSteps(item: GoalScoutWorkApi): Step[] {
    const { stage, outcome } = item
    const ended = stage === 'done' || stage === 'dropped'
    const failed = stage === 'stuck'
    const building = stage === 'building' || stage === 'review'
    const harmful = outcome === 'lost' || outcome === 'harmed'
    const ranDays =
        item.exposed_at && item.finished_at ? dayjs(item.finished_at).diff(dayjs(item.exposed_at), 'day') : null
    return [
        { label: 'Chosen', detail: shortDate(item.chosen_at), state: 'done' },
        {
            label: stage === 'building' ? 'Building' : stage === 'review' ? 'In review' : 'Built',
            detail: item.merged_at ? `merged ${shortDate(item.merged_at)}` : '',
            state: item.merged_at ? 'done' : failed ? 'failed' : building ? 'current' : 'todo',
        },
        {
            label: stage === 'live' ? 'Live' : 'Test',
            detail:
                stage === 'live'
                    ? `since ${shortDate(item.exposed_at)}`
                    : ranDays !== null
                      ? `ran ${ranDays} ${ranDays === 1 ? 'day' : 'days'}`
                      : '',
            state: stage === 'live' ? 'current' : ended && outcome && outcome !== 'dropped' ? 'done' : 'todo',
        },
        {
            label: ended ? (outcome === 'dropped' ? 'Stopped' : 'Decided') : 'Result',
            detail: shortDate(item.finished_at),
            state: ended ? (harmful ? 'failed' : 'done') : 'todo',
            tone: outcome === 'won' ? 'success' : harmful ? 'danger' : undefined,
        },
    ]
}

export function GoalTestSteps({ item }: { item: GoalScoutWorkApi }): JSX.Element {
    const steps = testSteps(item)
    return (
        <ol
            className="m-0 grid max-w-sm list-none p-0"
            style={{ gridTemplateColumns: `repeat(${steps.length}, minmax(0, 1fr))` }}
            aria-label="Test steps"
        >
            {steps.map((step, index) => (
                <li key={step.label} className="flex min-w-0 flex-col gap-1">
                    <span className="flex items-center">
                        <span className={cn('size-2.5 shrink-0 rounded-full border-2', DOT[step.state])} />
                        {index < steps.length - 1 && (
                            <span
                                className={cn(
                                    'h-px flex-1',
                                    step.state === 'done' ? 'bg-success' : 'bg-fill-highlight-100'
                                )}
                            />
                        )}
                    </span>
                    <span
                        className={cn(
                            'truncate pe-2 text-xs font-medium',
                            step.tone === 'success'
                                ? 'text-success'
                                : step.tone === 'danger'
                                  ? 'text-danger'
                                  : step.state === 'todo'
                                    ? 'text-tertiary'
                                    : 'text-primary'
                        )}
                    >
                        {step.label}
                    </span>
                    <span className="text-xs text-tertiary">{step.detail || ' '}</span>
                </li>
            ))}
        </ol>
    )
}
