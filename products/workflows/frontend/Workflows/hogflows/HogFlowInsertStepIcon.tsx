import clsx from 'clsx'

import { IconPlus } from '@posthog/icons'

/** The round + that adds a step, shared by the graph edges and the list gaps. Its trigger needs `group/insert`. */
export function HogFlowInsertStepIcon({
    active,
    size = 'small',
}: {
    active: boolean
    size?: 'small' | 'medium'
}): JSX.Element {
    return (
        <span
            className={clsx(
                'flex items-center justify-center rounded-full border bg-surface-primary text-secondary transition-colors group-hover/insert:border-accent group-hover/insert:text-accent group-focus-visible/insert:border-accent group-focus-visible/insert:text-accent',
                size === 'small' ? 'size-4' : 'size-6',
                active && 'border-accent text-accent'
            )}
        >
            <IconPlus className={size === 'small' ? 'size-3' : 'size-4'} />
        </span>
    )
}
