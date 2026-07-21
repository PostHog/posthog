import { useEffect, useRef, useState } from 'react'

import { IconCopy, IconExpand45, IconListCheck, IconX } from '@posthog/icons'
import { LemonButton, LemonModal } from '@posthog/lemon-ui'

import { copyToClipboard } from 'lib/utils/copyToClipboard'

import { MarkdownMessage } from '../messages/MarkdownMessage'

export interface PlanPayload {
    plan?: string
    planFilePath?: string
}

/**
 * Pull the plan markdown + plan file path out of an `ExitPlanMode` tool input. The agent-server sends
 * `rawInput: { plan, planFilePath, toolName }` — `plan` matching `/code`'s `toolCall.rawInput.plan`.
 */
export function getPlanPayload(input: Record<string, unknown> | undefined): PlanPayload {
    const plan = input?.plan
    const planFilePath = input?.planFilePath
    return {
        plan: typeof plan === 'string' && plan.trim() ? plan : undefined,
        planFilePath: typeof planFilePath === 'string' && planFilePath.trim() ? planFilePath : undefined,
    }
}

// Scroll offsets survive the card unmounting (collapse/expand, thread virtualization) — `/code` parity.
const planScrollPosition = new Map<string, number>()

export interface PlanCardProps {
    plan: string
    /** Stable id for the memoized markdown blocks and the preserved scroll offset. */
    id: string
}

/**
 * The agent's plan (the `ExitPlanMode` payload) as it appears in the thread — a port of `/code`'s
 * `PlanContent`: an accent-tinted document card capped at half the viewport with a "Final plan"
 * header bar (copy + fullscreen controls), and an expand-to-fullscreen view (a `LemonModal`) whose
 * header and content share the thread's centered max-width column. Esc exits fullscreen via the
 * modal's own close handling.
 */
export function PlanCard({ plan, id }: PlanCardProps): JSX.Element {
    const scrollRef = useRef<HTMLDivElement>(null)
    const [isFullscreen, setIsFullscreen] = useState(false)

    // Restore + track the scroll offset of whichever container is active (inline card or fullscreen body).
    useEffect(() => {
        const el = scrollRef.current
        if (!el) {
            return
        }

        const position = planScrollPosition.get(id)
        if (position !== undefined) {
            el.scrollTop = position
        }

        const handleScroll = (): void => {
            planScrollPosition.set(id, el.scrollTop)
        }
        el.addEventListener('scroll', handleScroll, { passive: true })
        return () => el.removeEventListener('scroll', handleScroll)
    }, [id, isFullscreen])

    const copyButton = (
        <LemonButton
            size="xsmall"
            icon={<IconCopy />}
            tooltip="Copy plan to clipboard"
            onClick={() => void copyToClipboard(plan, 'plan')}
        />
    )

    if (isFullscreen) {
        return (
            <LemonModal
                isOpen
                onClose={() => setIsFullscreen(false)}
                fullScreen
                simple
                hideCloseButton
                className="overflow-hidden"
            >
                <div className="flex h-full min-h-0 flex-col">
                    <div className="border-b px-4 py-2">
                        <div className="mx-auto flex w-full max-w-180 items-center justify-between">
                            <div className="flex items-center gap-2 text-accent">
                                <IconListCheck className="size-4" />
                                <span className="text-sm">Plan</span>
                            </div>
                            <div className="flex items-center gap-1">
                                {copyButton}
                                <LemonButton
                                    size="xsmall"
                                    icon={<IconX />}
                                    tooltip="Exit fullscreen (Escape)"
                                    onClick={() => setIsFullscreen(false)}
                                />
                            </div>
                        </div>
                    </div>
                    <div ref={scrollRef} className="min-h-0 flex-1 overflow-y-auto p-6">
                        <div className="mx-auto w-full max-w-180">
                            <MarkdownMessage content={plan} id={id} />
                        </div>
                    </div>
                </div>
            </LemonModal>
        )
    }

    // Mobile-first height cap: small screens get most of the viewport, `sm+` keeps /code's half-viewport cap.
    return (
        <div className="flex max-h-[75vh] max-w-[750px] flex-col overflow-hidden rounded-lg border-2 border-accent bg-accent-highlight-secondary sm:max-h-[50vh]">
            <div className="flex items-center justify-between gap-2 border-b border-accent px-3 py-1.5">
                <div className="flex min-w-0 items-center gap-2 text-accent">
                    <IconListCheck className="size-4 shrink-0" />
                    <span className="text-sm font-medium">Final plan</span>
                </div>
                <div className="flex shrink-0 items-center gap-1">
                    {copyButton}
                    <LemonButton
                        size="xsmall"
                        icon={<IconExpand45 />}
                        tooltip="Expand to fullscreen"
                        onClick={() => setIsFullscreen(true)}
                    />
                </div>
            </div>
            <div ref={scrollRef} className="min-h-0 flex-1 overflow-y-auto p-4">
                <MarkdownMessage content={plan} id={id} />
            </div>
        </div>
    )
}
