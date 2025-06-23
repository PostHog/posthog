import { Handle } from '@xyflow/react'

import { Optional } from '~/types'

export type StepViewNodeHandle = Omit<Optional<Handle, 'width' | 'height'>, 'nodeId'> & { label?: string }

export function StepView({
    name,
    icon,
    selected,
    handles,
    children,
}: {
    name: string
    selected: boolean
    handles: StepViewNodeHandle[]
    icon?: React.ReactNode
    children?: React.ReactNode
}): JSX.Element {
    return (
        <div
            // Keep in sync with NODE_WIDTH and NODE_HEIGHT (tailwind will not accept dynamic values)
            className={`w-[100px] h-[34px] bg-surface-primary border ${
                selected ? 'border-secondary' : 'border-primary'
            } rounded p-2 hover:bg-surface-secondary transition-transform duration-300 cursor-pointer`}
        >
            <div className="flex gap-1 justify-center items-center">
                {icon}
                <div className="text-xs">{name}</div>
            </div>
            {children}
            {handles.map((handle) => (
                // isConnectable={false} prevents edges from being manually added
                <Handle key={handle.id} {...handle} isConnectable={false} className="opacity-0" />
            ))}
        </div>
    )
}
