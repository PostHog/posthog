import { ChangeEvent, KeyboardEvent } from 'react'

import { Button, Kbd, KbdGroup, Text, Textarea } from '@posthog/quill-primitives'

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
    quote,
    autoFocus = false,
    rows = 2,
    showShortcut = true,
    dataAttr,
}: {
    value: string
    onChange: (value: string) => void
    onSubmit: () => void
    onCancel?: () => void
    /** This box's write is in flight. */
    saving: boolean
    /** Another write is in flight, so this one waits. */
    busy?: boolean
    label: string
    placeholder: string
    submitLabel?: string
    /** The selected text the comment is about. */
    quote?: string
    autoFocus?: boolean
    rows?: number
    showShortcut?: boolean
    dataAttr: string
}): JSX.Element {
    const submit = (): void => {
        if (value.trim() && !saving && !busy) {
            onSubmit()
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
            {quote && (
                <Text
                    size="xs"
                    variant="muted"
                    render={<blockquote />}
                    className="m-0 line-clamp-3 border-l-2 border-border pl-2 break-words whitespace-pre-wrap"
                >
                    {quote}
                </Text>
            )}
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
            <div className="flex items-center justify-end gap-2">
                {showShortcut && (
                    <KbdGroup className="mr-auto text-muted-foreground" aria-label="Keyboard shortcut to send">
                        <Kbd>{isMac() ? '⌘' : 'Ctrl'}</Kbd>
                        <Kbd>Enter</Kbd>
                    </KbdGroup>
                )}
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
                <Button
                    type="submit"
                    size="sm"
                    variant="primary"
                    loading={saving}
                    disabled={!value.trim() || busy}
                    data-attr={`${dataAttr}-submit`}
                >
                    {submitLabel}
                </Button>
            </div>
        </form>
    )
}
