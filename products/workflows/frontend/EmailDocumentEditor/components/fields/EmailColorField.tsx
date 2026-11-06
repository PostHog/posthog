import clsx from 'clsx'
import { useEffect, useState } from 'react'

import { IconX } from '@posthog/icons'
import { LemonButton, LemonInput } from '@posthog/lemon-ui'

import { EmailFieldRow } from './EmailFieldRow'

const HEX = /^#[0-9a-f]{6}$/i

export function EmailColorField({
    label,
    value,
    placeholder,
    onChange,
    attr,
}: {
    label: string
    value: string | undefined
    placeholder?: string
    onChange: (value: string | undefined) => void
    attr?: string
}): JSX.Element {
    const [text, setText] = useState(value ?? '')
    useEffect(() => setText(value ?? ''), [value])
    const shown = value || placeholder || '#ffffff'
    return (
        <EmailFieldRow label={label}>
            <input
                type="color"
                aria-label={`${label} color`}
                className={clsx(
                    'w-7 h-7 shrink-0 cursor-pointer rounded border p-0 bg-transparent',
                    !value && 'opacity-50'
                )}
                value={HEX.test(shown) ? shown : '#ffffff'}
                onChange={(event) => onChange(event.target.value)}
                data-attr={attr ? `${attr}-swatch` : undefined}
            />
            <LemonInput
                size="small"
                fullWidth
                value={text}
                placeholder={placeholder}
                onChange={(next) => {
                    setText(next)
                    if (next === '') {
                        onChange(undefined)
                    } else if (/^#([0-9a-f]{3}|[0-9a-f]{6}|[0-9a-f]{8})$/i.test(next) || /^[a-z]+$/i.test(next)) {
                        onChange(next)
                    }
                }}
                data-attr={attr}
            />
            {value !== undefined && placeholder !== undefined ? (
                <LemonButton
                    size="xsmall"
                    icon={<IconX />}
                    aria-label={`Clear ${label}`}
                    tooltip="Reset"
                    onClick={() => onChange(undefined)}
                />
            ) : null}
        </EmailFieldRow>
    )
}
