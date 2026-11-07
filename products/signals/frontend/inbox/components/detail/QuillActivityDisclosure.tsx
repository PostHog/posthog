import { IconChevronDown, IconChevronRight } from '@posthog/icons'
import { Button, cn } from '@posthog/quill'

/** The quill sibling of `ActivityDisclosure`: a toggle row that reveals its children below. */
export function QuillActivityDisclosure({
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
        <div className={cn('flex min-w-0 flex-col gap-1', className)}>
            <Button
                left={fullWidth}
                disabledReason={disabledReason}
                aria-expanded={expanded}
                onClick={() => onChange(!expanded)}
                className={cn('max-w-full font-normal text-muted-foreground', fullWidth ? 'w-full' : 'self-start')}
            >
                {expanded ? <IconChevronDown /> : <IconChevronRight />}
                {expanded && expandedLabel ? expandedLabel : label}
            </Button>
            {expanded ? <div className="min-w-0">{children}</div> : null}
        </div>
    )
}
