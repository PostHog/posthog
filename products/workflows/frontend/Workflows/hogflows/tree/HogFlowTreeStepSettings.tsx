import { useEffect, useState } from 'react'

import { cn } from 'lib/ui/quill'

import { HogFlowEditorPanelBuildDetail } from '../panel/HogFlowEditorPanelBuildDetail'

const prefersReducedMotion = (): boolean => window.matchMedia('(prefers-reduced-motion: reduce)').matches

export function HogFlowTreeStepSettings({ open, onClosed }: { open: boolean; onClosed: () => void }): JSX.Element {
    const [expanded, setExpanded] = useState(false)

    useEffect(() => {
        if (!open) {
            setExpanded(false)
            if (prefersReducedMotion()) {
                onClosed()
            }
            return
        }
        // Wait two frames: the browser must paint the collapsed state once, or it has no start height to animate from.
        let frame = requestAnimationFrame(() => {
            frame = requestAnimationFrame(() => setExpanded(true))
        })
        return () => cancelAnimationFrame(frame)
    }, [open, onClosed])

    return (
        <div
            className={cn(
                'grid transition-[grid-template-rows] duration-200 ease-out motion-reduce:transition-none',
                expanded ? 'grid-rows-[1fr]' : 'grid-rows-[0fr]'
            )}
            onTransitionEnd={(event) => {
                if (event.target === event.currentTarget && !open) {
                    onClosed()
                }
            }}
            data-attr="workflow-tree-step-settings"
        >
            <div className="min-h-0 overflow-hidden">
                <div className="flex flex-col border-t bg-card">
                    <HogFlowEditorPanelBuildDetail />
                </div>
            </div>
        </div>
    )
}
