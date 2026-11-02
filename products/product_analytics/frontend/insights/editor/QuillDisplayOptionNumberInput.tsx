import { useId } from 'react'

import { FieldLabel, InputGroup, InputGroupAddon, InputGroupInput, InputGroupText } from '@posthog/quill'

import { QuillDisplayOptionInfo } from './QuillDisplayOptionInfo'
import { QuillDisplayOptionRow } from './QuillDisplayOptionRow'

export interface QuillDisplayOptionNumberInputProps {
    label: string
    hideLabel?: boolean
    info?: string
    value: number | undefined
    onChange: (value: number | undefined) => void
    onCommit?: () => void
    min?: number
    max?: number
    suffix?: string
    placeholder?: string
    disabledReason?: string | null
    'data-attr'?: string
}

export function QuillDisplayOptionNumberInput({
    label,
    hideLabel,
    info,
    value,
    onChange,
    onCommit,
    min,
    max,
    suffix,
    placeholder,
    disabledReason,
    'data-attr': dataAttr,
}: QuillDisplayOptionNumberInputProps): JSX.Element {
    const id = useId()
    const disabled = !!disabledReason

    return (
        <QuillDisplayOptionRow disabledReason={disabledReason}>
            {!hideLabel && (
                <FieldLabel htmlFor={id} className="items-center gap-1 font-normal">
                    {label}
                    {info && <QuillDisplayOptionInfo info={info} />}
                </FieldLabel>
            )}
            <InputGroup className={hideLabel ? 'w-full' : 'w-28'} aria-disabled={disabled || undefined}>
                <InputGroupInput
                    id={id}
                    type="number"
                    aria-label={hideLabel ? label : undefined}
                    value={value ?? ''}
                    min={min}
                    max={max}
                    step={1}
                    placeholder={placeholder}
                    disabled={disabled}
                    data-attr={dataAttr}
                    onChange={(event) => {
                        const next = event.target.valueAsNumber
                        onChange(Number.isFinite(next) ? next : undefined)
                    }}
                    onBlur={onCommit}
                    onKeyDown={(event) => {
                        if (event.key === 'Enter') {
                            onCommit?.()
                        }
                    }}
                />
                {suffix && (
                    <InputGroupAddon align="inline-end">
                        <InputGroupText>{suffix}</InputGroupText>
                    </InputGroupAddon>
                )}
            </InputGroup>
        </QuillDisplayOptionRow>
    )
}
