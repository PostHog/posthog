import { ChangeEvent, KeyboardEvent, useId, useState } from 'react'

import { Button, Checkbox, Label, Textarea, Tooltip, TooltipContent, TooltipTrigger } from '@posthog/quill-primitives'

import { isMac } from 'lib/utils/dom'

/** A comment box with a send button. Cmd+Enter or Ctrl+Enter sends, and Escape cancels. */
export function ArtifactCommentComposer({
    value,
    onChange,
    onSubmit,
    onCancel,
    saving,
    busy = false,
    label,
    placeholder,
    submitLabel = 'Comment',
    autoFocus = false,
    rows = 2,
    dataAttr,
}: {
    value: string
    onChange: (value: string) => void
    onSubmit: (addToChat: boolean) => void
    onCancel?: () => void
    /** This box's write is in flight. */
    saving: boolean
    /** Another write is in flight, so this one waits. */
    busy?: boolean
    label: string
    placeholder: string
    submitLabel?: string
    autoFocus?: boolean
    rows?: number
    dataAttr: string
}): JSX.Element {
    const [addToChat, setAddToChat] = useState(false)
    const addToChatId = useId()
    const submit = (): void => {
        if (value.trim() && !saving && !busy) {
            onSubmit(addToChat)
        }
    }
    return (
        <form
            className="flex flex-col gap-2"
            onSubmit={(event) => {
                event.preventDefault()
                submit()
            }}
        >
            <Textarea
                autoFocus={autoFocus}
                aria-label={label}
                placeholder={placeholder}
                rows={rows}
                value={value}
                disabled={saving}
                onChange={(event: ChangeEvent<HTMLTextAreaElement>) => onChange(event.target.value)}
                onKeyDown={(event: KeyboardEvent<HTMLTextAreaElement>) => {
                    if (event.key === 'Enter' && (event.metaKey || event.ctrlKey)) {
                        event.preventDefault()
                        submit()
                    } else if (event.key === 'Escape' && onCancel) {
                        event.preventDefault()
                        onCancel()
                    }
                }}
                data-attr={`${dataAttr}-input`}
            />
            <div className="flex flex-wrap items-center justify-end gap-2">
                <div className="mr-auto flex items-center gap-1.5">
                    <Checkbox
                        id={addToChatId}
                        size="sm"
                        checked={addToChat}
                        disabled={saving}
                        onCheckedChange={(checked: boolean) => setAddToChat(checked)}
                        data-attr={`${dataAttr}-add-to-chat`}
                    />
                    <Label htmlFor={addToChatId} className="text-xs text-muted-foreground">
                        Add to chat
                    </Label>
                </div>
                {onCancel && (
                    <Button
                        type="button"
                        size="sm"
                        variant="outline"
                        disabled={saving}
                        onClick={onCancel}
                        data-attr={`${dataAttr}-cancel`}
                    >
                        Cancel
                    </Button>
                )}
                <Tooltip>
                    <TooltipTrigger
                        render={
                            <Button
                                type="submit"
                                size="sm"
                                variant="primary"
                                loading={saving}
                                disabled={!value.trim() || busy}
                                data-attr={`${dataAttr}-submit`}
                            />
                        }
                    >
                        {submitLabel}
                    </TooltipTrigger>
                    <TooltipContent>{`Press ${isMac() ? '⌘' : 'Ctrl'} + Enter to send`}</TooltipContent>
                </Tooltip>
            </div>
        </form>
    )
}
