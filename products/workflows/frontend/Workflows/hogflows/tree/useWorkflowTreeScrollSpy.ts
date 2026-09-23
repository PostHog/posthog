import { useEffect, useState } from 'react'
import type { RefObject } from 'react'

const STEP_SELECTOR = '[data-attr="workflow-tree-step"]'

// Returns the element id of the first step card that is visible below the given offset. The
// offset leaves out the space that a bar fixed to the top of the scroll area covers.
export function useWorkflowTreeScrollSpy(
    treeRef: RefObject<HTMLElement>,
    enabled: boolean,
    topOffset: number,
    layoutVersion: unknown
): string | null {
    const [activeStepId, setActiveStepId] = useState<string | null>(null)

    useEffect(() => {
        const tree = treeRef.current
        const viewport = tree?.closest<HTMLElement>('[data-slot="scroll-area-viewport"]')
        if (!enabled || !tree || !viewport) {
            setActiveStepId(null)
            return
        }

        let frame: number | null = null
        const update = (): void => {
            frame = null
            const limit = viewport.getBoundingClientRect().top + topOffset
            const steps = Array.from(tree.querySelectorAll<HTMLElement>(STEP_SELECTOR))
            const visibleStep = steps.find((step) => step.getBoundingClientRect().bottom > limit) ?? steps.at(-1)
            setActiveStepId(visibleStep?.id ?? null)
        }
        const schedule = (): void => {
            if (frame === null) {
                frame = requestAnimationFrame(update)
            }
        }

        update()
        viewport.addEventListener('scroll', schedule, { passive: true })
        const resizeObserver = typeof ResizeObserver === 'undefined' ? null : new ResizeObserver(schedule)
        resizeObserver?.observe(tree)

        return () => {
            viewport.removeEventListener('scroll', schedule)
            resizeObserver?.disconnect()
            if (frame !== null) {
                cancelAnimationFrame(frame)
            }
        }
    }, [treeRef, enabled, topOffset, layoutVersion])

    return activeStepId
}
