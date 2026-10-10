import { useEffect, useState } from 'react'

import { Button, Input, Popover, PopoverContent, PopoverTrigger, Text } from '@posthog/quill'

export interface SeriesExpressionPopoverProps {
    open: boolean
    onOpenChange: (open: boolean) => void
    expression: string
    onApply: (expression: string) => void
}

/** Edits the SQL expression an event is measured with. A menu item opens it, so it has no trigger of its own. */
export function SeriesExpressionPopover({
    open,
    onOpenChange,
    expression,
    onApply,
}: SeriesExpressionPopoverProps): JSX.Element {
    const [draft, setDraft] = useState(expression)

    useEffect(() => {
        if (open) {
            setDraft(expression)
        }
    }, [open, expression])

    const apply = (): void => {
        if (draft.trim()) {
            onApply(draft)
            onOpenChange(false)
        }
    }

    return (
        <Popover open={open} onOpenChange={(nextOpen) => onOpenChange(nextOpen)}>
            {/* An anchor with no size. It keeps the popover beside the word whose menu opened it. */}
            <PopoverTrigger nativeButton={false} tabIndex={-1} render={<span aria-hidden className="inline-block" />} />
            <PopoverContent align="start" aria-label="SQL expression" className="w-96 gap-3">
                <Text size="xs" variant="muted">
                    Write a SQL expression that returns one number, for example count() / uniq(person_id).
                </Text>
                <Input
                    value={draft}
                    placeholder="count()"
                    aria-label="SQL expression"
                    className="font-mono"
                    onChange={(event: React.ChangeEvent<HTMLInputElement>) => setDraft(event.target.value)}
                    onKeyDown={(event: React.KeyboardEvent<HTMLInputElement>) => {
                        if (event.key === 'Enter') {
                            apply()
                        }
                    }}
                    data-attr="quill-insight-measure-expression-input"
                />
                <Button
                    variant="primary"
                    size="sm"
                    className="self-end"
                    onClick={apply}
                    data-attr="quill-insight-measure-expression-apply"
                >
                    Apply
                </Button>
            </PopoverContent>
        </Popover>
    )
}
