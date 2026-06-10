import { JSX, useMemo, useState } from 'react'

import type { Plan } from './acp-types'
import { getPlanStats } from './derivePlan'
import { IconChevronDown, IconChevronRight } from './primitives/icons'
import { type Step, StepIcon, StepList } from './StepList'

/**
 * Ported from apps/code/src/renderer/features/sessions/components/PlanStatusBar.tsx.
 * Compact progress bar for the live plan, rendered above the composer. Click to
 * expand the full entry list (reuses StepList for the icons and rows).
 */

function planEntriesToSteps(plan: Plan): Step[] {
    // Index-prefixed keys: plan entries have no id and content can repeat.
    return plan.entries.map((entry, index) => ({
        key: `${index}-${entry.content}`,
        label: entry.content,
        status: entry.status ?? 'pending',
    }))
}

interface PlanStatusBarProps {
    plan: Plan | null
}

export function PlanStatusBar({ plan }: PlanStatusBarProps): JSX.Element | null {
    const [isExpanded, setIsExpanded] = useState(false)

    const stats = useMemo(() => (plan?.entries?.length ? getPlanStats(plan) : null), [plan])

    if (!plan || !stats || stats.allCompleted) {
        return null
    }

    return (
        <div
            className="cursor-pointer border-t border-border bg-bg-light"
            role="button"
            aria-expanded={isExpanded}
            onClick={() => setIsExpanded(!isExpanded)}
        >
            <div className="mx-auto max-w-4xl">
                <div className="flex items-center gap-2 px-3 py-2">
                    {isExpanded ? (
                        <IconChevronDown className="shrink-0 text-muted" style={{ fontSize: 12 }} />
                    ) : (
                        <IconChevronRight className="shrink-0 text-muted" style={{ fontSize: 12 }} />
                    )}
                    <span className="whitespace-nowrap text-[13px] text-muted">
                        {stats.completed}/{stats.total} completed
                    </span>
                    {stats.inProgress && (
                        <>
                            <span className="text-[13px] text-muted">•</span>
                            <StepIcon status="in_progress" />
                            <span className="truncate text-[13px] text-default">{stats.inProgress.content}</span>
                        </>
                    )}
                </div>
                {isExpanded && (
                    <div className="border-t border-border px-3 pt-2 pb-2">
                        <StepList steps={planEntriesToSteps(plan)} size="1" />
                    </div>
                )}
            </div>
        </div>
    )
}
