import { JSX, useEffect, useState } from 'react'

import { LemonCollapse } from '@posthog/lemon-ui'

import { Step, StepList } from '../StepList'

interface ProgressGroupViewProps {
    steps: Step[]
    /** True while at least one step in this group is `in_progress`. */
    isActive: boolean
    /** True once the enclosing turn has finished. Drives the auto-collapse. */
    turnComplete?: boolean
}

// Header label follows the stream: the currently in-flight step's label if
// any, otherwise the last step seen. No hardcoded fallbacks — the backend
// controls all wording, including present-tense during `in_progress`.
function resolveHeaderLabel(steps: Step[]): string | null {
    if (steps.length === 0) {
        return null
    }
    const active = steps.find((s) => s.status === 'in_progress')
    if (active) {
        return active.label
    }
    return steps[steps.length - 1].label
}

const PANEL_KEY = 'progress'

export function ProgressGroupView({ steps, isActive, turnComplete }: ProgressGroupViewProps): JSX.Element | null {
    // Multi-step groups always render a collapsible header (caret + summary).
    // While the turn is still running the trigger is disabled and forced open,
    // so the user sees progress stream in without a flicker between consecutive
    // step transitions. Once the turn completes, the header auto-collapses and
    // becomes interactive. Single-step groups have no header at all — the one
    // step row IS the whole view.
    const [userToggledOpen, setUserToggledOpen] = useState<boolean | null>(null)

    useEffect(() => {
        // Any reactivation clears the sticky user choice so a new round of work
        // starts expanded again.
        if (isActive) {
            setUserToggledOpen(null)
        }
    }, [isActive])

    if (steps.length === 0) {
        return null
    }

    const hasHeader = steps.length > 1

    // Single-step groups have no header, so their body must stay expanded —
    // collapsing with no header would leave nothing on screen. They render the
    // StepList directly without any collapse chrome.
    if (!hasHeader) {
        return (
            <div className="my-1 py-1">
                <StepList steps={steps} />
            </div>
        )
    }

    // Multi-step groups stay open while the turn is running, then honour the
    // user toggle once the turn completes (default: collapsed).
    const isOpen = !turnComplete ? true : (userToggledOpen ?? false)
    const summaryLabel = resolveHeaderLabel(steps) ?? ''

    return (
        <div className="my-1">
            <LemonCollapse
                embedded
                activeKey={isOpen ? PANEL_KEY : undefined}
                onChange={(next) => {
                    // The trigger is inert until the turn completes, mirroring the
                    // reference's `disabled={!turnComplete}` collapsible trigger.
                    if (turnComplete) {
                        setUserToggledOpen(next === PANEL_KEY)
                    }
                }}
                panels={[
                    {
                        key: PANEL_KEY,
                        header: <span className="text-sm font-medium text-default">{summaryLabel}</span>,
                        content: (
                            <div className="py-1">
                                <StepList steps={steps} />
                            </div>
                        ),
                    },
                ]}
            />
        </div>
    )
}
