import { useEffect, useRef, useState } from 'react'

import { LemonButton, LemonInput, Spinner } from '@posthog/lemon-ui'

import { cn } from 'lib/utils/css-classes'

export interface Option {
    label: string
    value: string
    icon?: JSX.Element
    description?: string
}

interface OptionSelectorProps {
    options: Option[]
    onSelect: (value: string | null) => void
    allowCustom?: boolean
    customPlaceholder?: string
    onCustomSubmit?: (value: string) => void
    disabled?: boolean
    loading?: boolean
    loadingMessage?: string
    /** Initial value for the custom input (used when editing a previous answer) */
    initialCustomValue?: string
    /** Currently selected value (used to highlight the selected option) */
    selectedValue?: string
    /** Label for the submit button (default: "Next") */
    submitLabel?: string
    /** Called when the user clicks "Skip question" */
    onSkip?: () => void
    /**
     * When true, picking an option only stages the selection (via `onSelect`) — the answer is not
     * committed until the user clicks the always-visible submit button, which calls `onSubmit`. This
     * prevents a single stray click or keypress from submitting the first/recommended answer, and gives
     * mobile users a visible control to confirm with. When false (default) picking an option commits it
     * immediately, matching the legacy advance-on-pick flow.
     */
    requireSubmit?: boolean
    /** Called when the user commits a staged option via the submit button (only used with `requireSubmit`). */
    onSubmit?: () => void
}

export function OptionSelector({
    options,
    onSelect,
    allowCustom = false,
    customPlaceholder = 'Type your response...',
    onCustomSubmit,
    disabled = false,
    loading = false,
    loadingMessage = 'Processing...',
    initialCustomValue,
    selectedValue,
    submitLabel = 'Next',
    onSkip,
    requireSubmit = false,
    onSubmit,
}: OptionSelectorProps): JSX.Element {
    const isCustomValue = selectedValue !== undefined && !options.some((o) => o.value === selectedValue)
    const [userWantsCustomMode, setUserWantsCustomMode] = useState(isCustomValue)
    const showCustomInput = userWantsCustomMode || isCustomValue
    const [customInput, setCustomInput] = useState(initialCustomValue ?? '')
    const selectedValueRef = useRef(selectedValue)
    selectedValueRef.current = selectedValue

    useEffect(() => {
        if (disabled || loading) {
            return
        }

        function handleKeyDown(event: KeyboardEvent): void {
            if (showCustomInput && event.key === 'Escape') {
                event.preventDefault()
                setUserWantsCustomMode(false)
                setCustomInput('')
                return
            }

            // Don't trigger keyboard shortcuts when typing in an input
            if (event.target instanceof HTMLInputElement || event.target instanceof HTMLTextAreaElement) {
                return
            }

            for (const [index, option] of options.entries()) {
                if (event.key === String(index + 1)) {
                    event.preventDefault()
                    if (selectedValueRef.current === option.value) {
                        onSelect(null)
                    } else {
                        setUserWantsCustomMode(false)
                        onSelect(option.value)
                    }
                    return
                }
            }

            if (allowCustom && event.key === String(options.length + 1)) {
                event.preventDefault()
                setUserWantsCustomMode(true)
            }
        }

        window.addEventListener('keydown', handleKeyDown)
        return () => {
            window.removeEventListener('keydown', handleKeyDown)
        }
    }, [options, onSelect, allowCustom, disabled, loading, showCustomInput])

    const noDescriptions = options.every((o) => !o.description)

    const handleCustomSubmit = (): void => {
        if (!customInput.trim()) {
            // When not choosing a custom input, hide the input and show button again
            setUserWantsCustomMode(false)

            return
        }
        setUserWantsCustomMode(false)
        if (requireSubmit) {
            // Stage the typed answer, then commit it through the same submit path as a picked option.
            onSelect(customInput.trim())
            onSubmit?.()
            return
        }
        onCustomSubmit?.(customInput.trim())
    }

    if (loading) {
        return (
            <div className="flex items-center gap-2 text-muted">
                <Spinner className="size-4" />
                <span>{loadingMessage}</span>
            </div>
        )
    }

    return (
        <div
            className={cn('flex flex-col gap-1.5', {
                // When there are no descriptions, reduce the gap between options to 0.5
                'gap-0.5': noDescriptions,
            })}
        >
            <div className="flex flex-col gap-2 font-medium">
                {options.map((o) => (
                    <label
                        key={o.value}
                        className="grid items-center gap-x-2 grid-cols-[min-content_auto] text-sm cursor-pointer"
                        onClick={(e) => {
                            e.preventDefault()
                            if (selectedValue === o.value) {
                                onSelect(null)
                            } else {
                                setUserWantsCustomMode(false)
                                onSelect(o.value)
                            }
                        }}
                    >
                        <input
                            type="radio"
                            className="cursor-pointer"
                            checked={selectedValue === o.value && !showCustomInput}
                            onChange={() => {}}
                        />
                        <span>{o.label}</span>
                        {o.description && (
                            <div className="text-secondary font-normal row-start-2 col-start-2 text-pretty text-xs">
                                {o.description}
                            </div>
                        )}
                    </label>
                ))}
            </div>

            {allowCustom && (
                <label className="grid items-center gap-x-2 grid-cols-[min-content_auto] text-sm font-medium cursor-pointer">
                    <input
                        type="radio"
                        className="cursor-pointer"
                        checked={showCustomInput}
                        onChange={() => {
                            setUserWantsCustomMode(true)
                        }}
                        value="custom"
                    />
                    {showCustomInput ? (
                        <LemonInput
                            placeholder={customPlaceholder}
                            fullWidth
                            size="small"
                            value={customInput}
                            onChange={setCustomInput}
                            onPressEnter={handleCustomSubmit}
                            autoFocus={true}
                        />
                    ) : (
                        <span className="my-1.5">Explain what you'd like instead.</span>
                    )}
                </label>
            )}
            {(onSkip || showCustomInput || requireSubmit) && (
                <div className="flex items-center justify-between gap-2 pt-2">
                    {onSkip && (
                        <LemonButton type="secondary" size="small" onClick={onSkip}>
                            Skip question
                        </LemonButton>
                    )}
                    {showCustomInput ? (
                        <LemonButton
                            type="primary"
                            size="small"
                            disabledReason={!customInput.trim() ? 'Please type a response' : undefined}
                            onClick={handleCustomSubmit}
                            className="ml-auto"
                        >
                            {submitLabel}
                        </LemonButton>
                    ) : requireSubmit ? (
                        <LemonButton
                            type="primary"
                            size="small"
                            disabledReason={selectedValue === undefined ? 'Select an option to continue' : undefined}
                            onClick={() => onSubmit?.()}
                            className="ml-auto"
                        >
                            {submitLabel}
                        </LemonButton>
                    ) : null}
                </div>
            )}
        </div>
    )
}
