import './AdventCalendar.scss'

import { Handle, Position } from '@xyflow/react'

import { IconCalendar } from '@posthog/icons'

export function AdventTriggerNode(): JSX.Element {
    return (
        <div className="relative size-14">
            <Handle
                id="out-right"
                type="source"
                position={Position.Right}
                isConnectable={false}
                className="!pointer-events-none !opacity-0"
            />
            <div className="AdventTrigger flex size-full items-center justify-center border-2 border-accent bg-surface-primary text-3xl text-accent shadow-sm">
                <IconCalendar />
            </div>
            <span className="pointer-events-none absolute left-1/2 top-full mt-1 -translate-x-1/2 whitespace-nowrap rounded bg-surface-primary px-1 text-[11px] leading-4 text-secondary">
                When: December
            </span>
        </div>
    )
}
