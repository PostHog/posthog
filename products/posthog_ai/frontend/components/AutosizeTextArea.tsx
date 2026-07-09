import './AutosizeTextArea.scss'

import React, { useRef } from 'react'
import TextareaAutosize from 'react-textarea-autosize'

import { cn } from 'lib/utils/css-classes'

// Native CSS autosizing where supported. The JS fallback (react-textarea-autosize) calls
// getComputedStyle on every keystroke, which forces a synchronous whole-document style recalc —
// hundreds of ms on threads with lots of mounted content.
const SUPPORTS_FIELD_SIZING = typeof CSS !== 'undefined' && CSS.supports('field-sizing', 'content')

export interface AutosizeTextAreaProps extends Pick<
    React.TextareaHTMLAttributes<HTMLTextAreaElement>,
    'id' | 'placeholder' | 'disabled' | 'maxLength' | 'onFocus' | 'onBlur' | 'onKeyDown' | 'aria-describedby'
> {
    value?: string
    onChange?: (newValue: string) => void
    /** Called when Enter is pressed without Shift (Shift+Enter inserts a newline). */
    onPressEnter?: (currentValue: string) => void
    /** Called when Cmd/Ctrl+Enter is pressed (plain Enter inserts a newline). */
    onPressCmdEnter?: (currentValue: string) => void
    minRows?: number
    maxRows?: number
    autoFocus?: boolean
    /** Classes for the wrapper element around the textarea. */
    className?: string
    /**
     * Classes for the `<textarea>` itself. Padding utilities belong here (not on the wrapper), so the
     * text is inset while the scrollbar still renders at the textarea's true edge.
     */
    textareaClassName?: string
    /** Skip the `input-like` border/focus frame around the textarea. */
    hideFocus?: boolean
    'data-attr'?: string
}

/** A self-sizing `textarea` for the agent composer surfaces. */
export const AutosizeTextArea = React.forwardRef<HTMLTextAreaElement, AutosizeTextAreaProps>(function AutosizeTextArea(
    {
        className,
        textareaClassName,
        onChange,
        onPressEnter,
        onPressCmdEnter,
        minRows = 1,
        maxRows,
        onKeyDown,
        autoFocus,
        hideFocus = false,
        ...textProps
    },
    ref
): JSX.Element {
    const _ref = useRef<HTMLTextAreaElement | null>(null)
    const textRef = ref || _ref

    const textareaClasses = cn('AutosizeTextArea w-full rounded', textareaClassName)
    const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>): void => {
        if (e.key === 'Enter' && !e.nativeEvent.isComposing) {
            const target = e.currentTarget
            // When shift is pressed, we always just want to add a new line
            if (!e.shiftKey) {
                if ((e.metaKey || e.ctrlKey) && onPressCmdEnter) {
                    onPressCmdEnter(target.value)
                    e.preventDefault()
                } else if (onPressEnter) {
                    onPressEnter(target.value)
                    e.preventDefault()
                }
            }
        }
        onKeyDown?.(e)
    }
    const handleChange = (event: React.ChangeEvent<HTMLTextAreaElement>): void => {
        onChange?.(event.currentTarget.value ?? '')
    }

    return (
        <div className={cn('flex flex-col rounded', !hideFocus && 'input-like', className)}>
            {SUPPORTS_FIELD_SIZING ? (
                <textarea
                    ref={textRef}
                    className={cn('AutosizeTextArea--native', textareaClasses)}
                    style={
                        {
                            '--autosize-textarea-min-rows': minRows,
                            '--autosize-textarea-max-rows': maxRows,
                        } as React.CSSProperties
                    }
                    onKeyDown={handleKeyDown}
                    onChange={handleChange}
                    autoFocus={!!autoFocus}
                    {...textProps}
                />
            ) : (
                <TextareaAutosize
                    minRows={minRows}
                    maxRows={maxRows}
                    ref={textRef}
                    className={textareaClasses}
                    onKeyDown={handleKeyDown}
                    onChange={handleChange}
                    autoFocus={!!autoFocus}
                    {...textProps}
                />
            )}
        </div>
    )
})
