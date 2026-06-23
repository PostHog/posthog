import { useRef } from 'react'

import { IconArrowRight } from '@posthog/icons'
import { LemonButton, LemonTextArea } from '@posthog/lemon-ui'

import { cn } from 'lib/utils/css-classes'

export interface SandboxComposerProps {
    value: string
    onChange: (value: string) => void
    onSubmit: () => void
    placeholder?: string
    /** Shows the send button as in-flight and blocks submission while true. */
    loading?: boolean
    /** Extra reason to block the send button (empty input is handled internally). */
    disabledReason?: string
    autoFocus?: boolean
    className?: string
}

/**
 * Presentational composer shell for the sandbox run surface. Borrows the PostHog AI input look
 * (bordered rounded container, large textarea with an overlaid placeholder, an absolutely-positioned
 * primary send button) without any of PostHog AI's conversation-only features — no slash commands,
 * hands-free, AI consent, queue editing, support override, or scene context chips. It holds no draft
 * or send state of its own: callers own the value and the submit handler.
 */
export function SandboxComposer({
    value,
    onChange,
    onSubmit,
    placeholder = 'Send a follow-up message…',
    loading = false,
    disabledReason,
    autoFocus,
    className,
}: SandboxComposerProps): JSX.Element {
    const textAreaRef = useRef<HTMLTextAreaElement>(null)

    const sendDisabledReason = !value.trim() ? 'Type a message first' : loading ? 'Sending…' : disabledReason

    const submit = (): void => {
        if (sendDisabledReason) {
            textAreaRef.current?.focus()
            return
        }
        onSubmit()
    }

    return (
        <div className={cn('relative w-full flex flex-col', className)}>
            <label
                htmlFor="sandbox-composer-input"
                className={cn(
                    'input-like flex flex-col cursor-text',
                    'border border-primary rounded-lg',
                    'bg-[var(--color-bg-fill-input)]',
                    '[--input-ring-size:2px] [--input-ring-color:var(--color-ai)]'
                )}
            >
                <div className="relative w-full">
                    {!value && (
                        <div
                            id="sandbox-composer-hint"
                            className="text-secondary absolute top-4 left-4 text-sm pointer-events-none"
                        >
                            {placeholder}
                        </div>
                    )}
                    <LemonTextArea
                        id="sandbox-composer-input"
                        aria-describedby={!value ? 'sandbox-composer-hint' : undefined}
                        data-attr="sandbox-composer-input"
                        ref={textAreaRef}
                        value={value}
                        onChange={onChange}
                        onPressCmdEnter={submit}
                        minRows={1}
                        maxRows={10}
                        className="!border-none !bg-transparent min-h-16 py-2 pl-2 pr-12 resize-none"
                        hideFocus
                        autoFocus={autoFocus}
                    />
                </div>
            </label>
            <div className="absolute flex items-center bottom-[7px] right-[7px]">
                <LemonButton
                    data-attr="sandbox-composer-send"
                    type="primary"
                    size="small"
                    icon={<IconArrowRight />}
                    onClick={submit}
                    loading={loading}
                    disabledReason={sendDisabledReason}
                    tooltip={sendDisabledReason ? undefined : "Let's go!"}
                />
            </div>
        </div>
    )
}
