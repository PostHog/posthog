import { IconChevronDown, IconChevronRight } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { cn } from 'lib/utils/css-classes'

export function ActivityDisclosure({
    expanded,
    onChange,
    label,
    expandedLabel,
    children,
    disabledReason,
    fullWidth = false,
    className,
}: {
    expanded: boolean
    onChange: (expanded: boolean) => void
    label: React.ReactNode
    expandedLabel?: React.ReactNode
    children: React.ReactNode
    disabledReason?: string
    fullWidth?: boolean
    className?: string
}): JSX.Element {
    return (
        <div className={className}>
            <LemonButton
                size="xsmall"
                type="tertiary"
                fullWidth={fullWidth}
                disabledReason={disabledReason}
                onClick={() => onChange(!expanded)}
                icon={expanded ? <IconChevronDown /> : <IconChevronRight />}
                className={cn('max-w-full font-normal text-secondary', fullWidth && 'justify-start text-left')}
            >
                {expanded && expandedLabel ? expandedLabel : label}
            </LemonButton>
            {expanded ? <div className="mt-1 min-w-0">{children}</div> : null}
        </div>
    )
}
