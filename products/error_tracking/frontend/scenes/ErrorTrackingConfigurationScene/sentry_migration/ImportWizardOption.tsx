import { ReactNode } from 'react'

import { IconChevronRight } from '@posthog/icons'
import { Card, Text, cn } from '@posthog/quill'

export interface ImportWizardOptionProps {
    title: string
    description: string
    icon?: ReactNode
    selected?: boolean
    onClick: () => void
    dataAttr: string
}

export function ImportWizardOption({
    title,
    description,
    icon,
    selected = false,
    onClick,
    dataAttr,
}: ImportWizardOptionProps): JSX.Element {
    return (
        <Card size="sm" className="p-0">
            <button
                type="button"
                onClick={onClick}
                aria-pressed={selected}
                data-attr={dataAttr}
                className={cn(
                    'flex w-full min-w-0 cursor-pointer items-center gap-3 px-3 py-2.5 text-start hover:bg-fill-hover focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-ring/30',
                    selected && 'bg-fill-selected'
                )}
            >
                {icon}
                <span className="flex min-w-0 flex-1 flex-col gap-0.5">
                    <Text size="sm" weight="medium" render={<span />} className="block">
                        {title}
                    </Text>
                    <Text size="xs" variant="muted" render={<span />} className="block">
                        {description}
                    </Text>
                </span>
                <IconChevronRight className="shrink-0 text-muted-foreground" />
            </button>
        </Card>
    )
}
