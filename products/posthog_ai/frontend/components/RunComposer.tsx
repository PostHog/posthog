import { Composer } from './composer/Composer'

export interface RunComposerProps {
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
 * Prepackaged composer for the sandbox run surface — a thin composition of the logic-free
 * {@link Composer} primitives that reproduces the PostHog AI input look (bordered rounded container,
 * large textarea with an overlaid placeholder, an absolutely-positioned primary send button) without
 * any of PostHog AI's conversation-only features. It holds no draft or send state of its own: callers
 * own the value and the submit handler. Surfaces that need to slot extra chrome should compose the
 * `Composer.*` parts directly instead of using this wrapper.
 */
export function RunComposer({
    value,
    onChange,
    onSubmit,
    placeholder = 'Send a follow-up message…',
    loading = false,
    disabledReason,
    autoFocus,
    className,
}: RunComposerProps): JSX.Element {
    return (
        <Composer.Root
            value={value}
            onChange={onChange}
            onSubmit={onSubmit}
            loading={loading}
            disabledReason={disabledReason}
            className={className}
        >
            <Composer.Frame>
                <Composer.Field>
                    <Composer.Placeholder>{placeholder}</Composer.Placeholder>
                    <Composer.Textarea
                        data-attr="sandbox-composer-input"
                        submitShortcut="cmd-enter"
                        autoFocus={autoFocus}
                    />
                </Composer.Field>
            </Composer.Frame>
            <Composer.Submit data-attr="sandbox-composer-send" />
        </Composer.Root>
    )
}
