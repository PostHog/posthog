import { ReactNode, useState } from 'react'

import {
    Button,
    Collapsible,
    CollapsibleContent,
    CollapsibleHeader,
    CollapsibleTrigger,
    Text,
    cn,
} from '@posthog/quill'

export interface QuillDetailLine {
    /** The line's name, when it differs from the section title of the flag-off page. */
    name?: string
    text: ReactNode
    tone?: 'default' | 'risk'
}

export function QuillDetailSection({
    title,
    line,
    rightSlot,
    children,
    onToggleCollapsed,
}: {
    title: string
    line?: QuillDetailLine | null
    rightSlot?: ReactNode
    children: ReactNode
    onToggleCollapsed?: (collapsed: boolean) => void
}): JSX.Element {
    const [open, setOpen] = useState(false)
    const toggle = (next: boolean): void => {
        setOpen(next)
        onToggleCollapsed?.(!next)
    }

    return (
        <Collapsible open={open} onOpenChange={toggle} className="QuillDetailSection">
            <CollapsibleHeader>
                <CollapsibleTrigger iconOnly>{`Show ${(line?.name ?? title).toLowerCase()}`}</CollapsibleTrigger>
                <Button
                    variant="default"
                    className="h-auto min-w-0 flex-1 justify-start py-1.5 ps-7 pe-2 text-left"
                    aria-expanded={open}
                    onClick={() => toggle(!open)}
                    data-attr="inbox-report-detail-line"
                >
                    <span className="QuillDetailSection__row">
                        <span className="QuillDetailSection__name">{line?.name ?? title}</span>
                        {line?.text && (
                            <Text
                                size="sm"
                                variant="muted"
                                render={<span />}
                                className={cn(
                                    'QuillDetailSection__line flex min-w-0 items-center gap-1 font-normal',
                                    line.tone === 'risk' && 'QuillDetailSection__line--risk'
                                )}
                            >
                                {line.tone === 'risk' && <span aria-hidden className="QuillDetailSection__pip" />}
                                {line.text}
                            </Text>
                        )}
                    </span>
                </Button>
                {rightSlot && <div className="ms-auto shrink-0">{rightSlot}</div>}
            </CollapsibleHeader>
            <CollapsibleContent>
                {/* The body mounts only while open: several bodies fetch data or mount a run transcript. */}
                {open && <div className="QuillDetailSection__body">{children}</div>}
            </CollapsibleContent>
        </Collapsible>
    )
}
