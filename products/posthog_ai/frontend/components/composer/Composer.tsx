import {
    createContext,
    forwardRef,
    type HTMLAttributes,
    type ReactNode,
    type RefObject,
    useCallback,
    useContext,
    useId,
    useMemo,
    useRef,
} from 'react'

import { IconArrowRight, IconStopFilled } from '@posthog/icons'
import { LemonButton, LemonTextArea } from '@posthog/lemon-ui'

import { cn } from 'lib/utils/css-classes'

// Radix-style compound composer: a set of logic-free, presentational surfaces that reproduce the
// PostHog AI input look (see scenes/max/components/QuestionInput.tsx) without any of its conversation
// logic. `Composer.Root` owns nothing but the controlled value/submit plumbing it's handed; every
// other part is a styled slot that reads that plumbing from context. Consumers compose the parts and
// own all state.

interface ComposerContextValue {
    value: string
    onChange: (value: string) => void
    loading: boolean
    disabled: boolean
    /** Empty input / loading / caller's `disabledReason`, collapsed to a single reason (undefined when sendable). */
    sendDisabledReason: string | undefined
    /** True when the send button should swap to a Stop button (active turn + empty input + an `onStop` handler). */
    showStop: boolean
    /** Cancels the active turn; drives the Stop button that replaces send when `showStop`. */
    onStop: (() => void) | undefined
    /** Focuses the textarea when blocked, otherwise calls the caller's `onSubmit`. */
    submit: () => void
    textAreaRef: RefObject<HTMLTextAreaElement>
    /** Shared id linking `Frame` (htmlFor), `Textarea` (id) and `Placeholder` (describedby). */
    id: string
    isThreadVisible: boolean
}

const ComposerContext = createContext<ComposerContextValue | null>(null)

export function useComposerContext(): ComposerContextValue {
    const ctx = useContext(ComposerContext)
    if (!ctx) {
        throw new Error('Composer.* components must be rendered inside <Composer.Root>')
    }
    return ctx
}

export interface ComposerRootProps {
    value: string
    onChange: (value: string) => void
    onSubmit: () => void
    /** Marks the send button in-flight and blocks submission. */
    loading?: boolean
    /** Disables the textarea. */
    disabled?: boolean
    /** Extra reason to block sending, beyond the internally-handled empty input. */
    disabledReason?: string
    /** True while the agent is actively working a turn. With empty input, the send button becomes a Stop button. */
    isTurnActive?: boolean
    /** Cancels the active turn. Wired to the Stop button that replaces send when `isTurnActive` and input is empty. */
    onStop?: () => void
    /** Renders the sticky page-level chrome (bordered, blurred, bottom-pinned) around the input. */
    isSticky?: boolean
    /** Follow-up variant: tighter frame border/radius and send-button offset. */
    isThreadVisible?: boolean
    className?: string
    /** Applied to the outermost wrapper when sticky chrome is rendered. */
    containerClassName?: string
    /** Supply to read the textarea node from outside; otherwise an internal ref is used. */
    textAreaRef?: RefObject<HTMLTextAreaElement>
    /** Override the auto-generated id linking the label, textarea and placeholder. */
    id?: string
    children: ReactNode
}

const ComposerRoot = forwardRef<HTMLFormElement, ComposerRootProps>(function ComposerRoot(
    {
        value,
        onChange,
        onSubmit,
        loading = false,
        disabled = false,
        disabledReason,
        isTurnActive = false,
        onStop,
        isSticky = false,
        isThreadVisible = false,
        className,
        containerClassName,
        textAreaRef: textAreaRefProp,
        id: idProp,
        children,
    },
    ref
): JSX.Element {
    const internalRef = useRef<HTMLTextAreaElement>(null)
    const textAreaRef = textAreaRefProp ?? internalRef
    const generatedId = useId()
    const id = idProp ?? generatedId

    const sendDisabledReason = !value.trim() ? 'Type a message first' : loading ? 'Sending…' : disabledReason

    // While a turn is active with no drafted text, the send button becomes a Stop button (cancel the run)
    // rather than a disabled "Type a message first" — a follow-up with text still sends/queues as usual.
    const showStop = isTurnActive && !value.trim() && !loading && !!onStop

    // Focuses the textarea when blocked, otherwise submits — shared by the native form submit and the
    // textarea keyboard shortcuts.
    const submit = useCallback(() => {
        if (sendDisabledReason) {
            textAreaRef.current?.focus()
            return
        }
        onSubmit()
    }, [sendDisabledReason, textAreaRef, onSubmit])

    const ctx = useMemo<ComposerContextValue>(
        () => ({
            value,
            onChange,
            loading,
            disabled,
            sendDisabledReason,
            showStop,
            onStop,
            submit,
            textAreaRef,
            id,
            isThreadVisible,
        }),
        [
            value,
            onChange,
            loading,
            disabled,
            sendDisabledReason,
            showStop,
            onStop,
            submit,
            textAreaRef,
            id,
            isThreadVisible,
        ]
    )

    // The relative wrapper is the positioning context for the absolutely-placed Submit + Placeholder. It's a
    // real <form> so the send button is a native submit and Enter/Cmd+Enter route through `onSubmit`. The
    // forwarded ref always points to this form, regardless of chrome mode.
    const hasChrome = isSticky || isThreadVisible || !!containerClassName
    const positioned = (
        <form
            data-slot="composer-root"
            className={cn('relative w-full flex flex-col', hasChrome ? 'z-1' : className)}
            ref={ref}
            onSubmit={(e) => {
                e.preventDefault()
                submit()
            }}
        >
            {children}
        </form>
    )

    return (
        <ComposerContext.Provider value={ctx}>
            {hasChrome ? (
                <div
                    className={cn(
                        'w-full px-3',
                        (isSticky || isThreadVisible) && 'sticky bottom-0 z-10 max-w-180 self-center',
                        containerClassName
                    )}
                >
                    <div
                        className={cn(
                            'flex flex-col items-center',
                            isSticky && 'border border-primary rounded-lg backdrop-blur-sm bg-glass-bg-3000',
                            className
                        )}
                    >
                        {positioned}
                    </div>
                </div>
            ) : (
                positioned
            )}
        </ComposerContext.Provider>
    )
})

/** Free slot above the frame (banners, queue, notices). Logic-free. */
const ComposerBanner = forwardRef<HTMLDivElement, HTMLAttributes<HTMLDivElement>>(function ComposerBanner(
    { className, children, ...rest },
    ref
): JSX.Element {
    return (
        <div data-slot="composer-banner" ref={ref} className={className} {...rest}>
            {children}
        </div>
    )
})

/** The in-frame top row for context chips / attachments, above the textarea. */
const ComposerHeader = forwardRef<HTMLDivElement, HTMLAttributes<HTMLDivElement>>(function ComposerHeader(
    { className, children, ...rest },
    ref
): JSX.Element {
    return (
        <div data-slot="composer-header" ref={ref} className={cn('pt-2 px-2', className)} {...rest}>
            {children}
        </div>
    )
})

export interface ComposerFrameProps extends HTMLAttributes<HTMLLabelElement> {
    /** Toggles the AI focus-ring color (off while the agent is streaming, per QuestionInput). */
    ringActive?: boolean
}

/** The bordered, rounded `input-like` container with the AI focus ring; a `<label>` so clicks focus the textarea. */
const ComposerFrame = forwardRef<HTMLLabelElement, ComposerFrameProps>(function ComposerFrame(
    { className, children, ringActive = true, ...rest },
    ref
): JSX.Element {
    const { id, isThreadVisible } = useComposerContext()
    return (
        <label
            data-slot="composer-frame"
            htmlFor={id}
            ref={ref}
            className={cn(
                'input-like flex flex-col cursor-text',
                'border border-primary',
                'bg-[var(--color-bg-fill-input)]',
                isThreadVisible ? 'border-primary m-0.5 rounded-[7px]' : 'rounded-lg',
                '[--input-ring-size:2px]',
                ringActive && '[--input-ring-color:var(--color-ai)]',
                className
            )}
            {...rest}
        >
            {children}
        </label>
    )
})

/** Positioning context grouping the overlaid Placeholder and the Textarea. */
const ComposerField = forwardRef<HTMLDivElement, HTMLAttributes<HTMLDivElement>>(function ComposerField(
    { className, children, ...rest },
    ref
): JSX.Element {
    return (
        <div data-slot="composer-field" ref={ref} className={cn('relative w-full', className)} {...rest}>
            {children}
        </div>
    )
})

/** Overlaid hint shown only while the input is empty. */
const ComposerPlaceholder = forwardRef<HTMLDivElement, HTMLAttributes<HTMLDivElement>>(function ComposerPlaceholder(
    { className, children, ...rest },
    ref
): JSX.Element | null {
    const { value, id } = useComposerContext()
    if (value) {
        return null
    }
    return (
        <div
            data-slot="composer-placeholder"
            id={`${id}-hint`}
            ref={ref}
            className={cn('text-secondary absolute top-4 left-4 text-sm pointer-events-none', className)}
            {...rest}
        >
            {children}
        </div>
    )
})

export interface ComposerTextareaProps {
    className?: string
    autoFocus?: boolean
    minRows?: number
    maxRows?: number
    /** `'enter'` submits on Enter (PostHog AI), `'cmd-enter'` on Cmd/Ctrl+Enter (tasks composer). */
    submitShortcut?: 'enter' | 'cmd-enter'
    'data-attr'?: string
}

/** The textarea itself, wired to the context value/submit. */
function ComposerTextarea({
    className,
    autoFocus,
    minRows = 1,
    maxRows = 10,
    submitShortcut = 'enter',
    ...rest
}: ComposerTextareaProps): JSX.Element {
    const { value, onChange, submit, textAreaRef, disabled, id } = useComposerContext()
    // onPressEnter / onPressCmdEnter are mutually exclusive in LemonTextArea's type — pick one.
    const submitProps =
        submitShortcut === 'cmd-enter' ? { onPressCmdEnter: () => submit() } : { onPressEnter: () => submit() }
    return (
        <LemonTextArea
            id={id}
            aria-describedby={!value ? `${id}-hint` : undefined}
            ref={textAreaRef}
            value={value}
            onChange={onChange}
            disabled={disabled}
            minRows={minRows}
            maxRows={maxRows}
            autoFocus={autoFocus}
            className={cn('!border-none !bg-transparent min-h-16 py-2 pl-2 pr-12 resize-none', className)}
            hideFocus
            {...submitProps}
            {...rest}
        />
    )
}

/** The in-frame bottom row for pickers / actions. */
const ComposerFooter = forwardRef<HTMLDivElement, HTMLAttributes<HTMLDivElement>>(function ComposerFooter(
    { className, children, ...rest },
    ref
): JSX.Element {
    return (
        <div data-slot="composer-footer" ref={ref} className={cn('pb-2 pr-12', className)} {...rest}>
            {children}
        </div>
    )
})

export interface ComposerSubmitProps {
    icon?: JSX.Element | null
    tooltip?: ReactNode
    /** Positioned wrapper className. */
    className?: string
    'data-attr'?: string
}

/** The absolutely-positioned send cluster, sibling of Frame inside Root's relative wrapper. */
function ComposerSubmit({ icon, tooltip, className, ...rest }: ComposerSubmitProps): JSX.Element {
    const { sendDisabledReason, loading, showStop, onStop, isThreadVisible } = useComposerContext()
    return (
        <div
            data-slot="composer-submit"
            className={cn(
                'absolute flex items-center',
                isThreadVisible ? 'bottom-[9px] right-[9px]' : 'bottom-[7px] right-[7px]',
                className
            )}
        >
            {showStop ? (
                // Stop the active turn. `htmlType="button"` so it never submits the (empty) form; the Enter
                // shortcut still routes through `submit` and just focuses, so Stop stays a click-only affordance.
                <LemonButton
                    type="secondary"
                    size="small"
                    htmlType="button"
                    icon={<IconStopFilled />}
                    onClick={() => onStop?.()}
                    tooltip="Stop"
                    {...rest}
                />
            ) : (
                <LemonButton
                    type="primary"
                    size="small"
                    htmlType="submit"
                    icon={icon ?? <IconArrowRight />}
                    loading={loading}
                    disabledReason={sendDisabledReason}
                    tooltip={sendDisabledReason ? undefined : (tooltip ?? "Let's go!")}
                    {...rest}
                />
            )}
        </div>
    )
}

export const Composer = Object.assign(ComposerRoot, {
    Root: ComposerRoot,
    Banner: ComposerBanner,
    Frame: ComposerFrame,
    Header: ComposerHeader,
    Field: ComposerField,
    Placeholder: ComposerPlaceholder,
    Textarea: ComposerTextarea,
    Footer: ComposerFooter,
    Submit: ComposerSubmit,
})
