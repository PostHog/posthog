import { ReactNode } from 'react'

import { IconCheckCircle } from '@posthog/icons'

import { Tooltip } from 'lib/lemon-ui/Tooltip'
import { cn } from 'lib/utils/css-classes'

type SelectableCardProps = {
    title: ReactNode
    description: ReactNode
    selected: boolean
    onClick: () => void
    className?: string
    'data-attr'?: string
} & ({ disabled?: false; disabledReason?: never } | { disabled: boolean; disabledReason: string })

export function SelectableCard({
    title,
    description,
    selected,
    onClick,
    disabled,
    disabledReason,
    className,
    'data-attr': dataAttr,
}: SelectableCardProps): JSX.Element {
    const card = (
        <div
            className={cn(
                'flex-1 cursor-pointer p-4 rounded border transition-colors',
                {
                    'border-accent bg-accent-highlight-secondary': selected,
                    'border-primary': !selected,
                    'hover:border-accent-dark': !disabled,
                    'opacity-50 cursor-not-allowed': disabled,
                },
                className
            )}
            onClick={disabled ? undefined : onClick}
            role="button"
            tabIndex={disabled ? -1 : 0}
            onKeyDown={(e) => {
                if (!disabled && (e.key === 'Enter' || e.key === ' ')) {
                    e.preventDefault()
                    onClick()
                }
            }}
            aria-pressed={selected}
            aria-disabled={disabled}
            data-attr={dataAttr}
        >
            <div className="font-semibold flex justify-between items-center">
                <span>{title}</span>
                {selected && <IconCheckCircle fontSize={18} color="var(--color-accent)" />}
            </div>
            <div className="text-secondary text-sm leading-relaxed mt-1">{description}</div>
        </div>
    )

    if (disabled && disabledReason) {
        return <Tooltip title={disabledReason}>{card}</Tooltip>
    }

    return card
}
