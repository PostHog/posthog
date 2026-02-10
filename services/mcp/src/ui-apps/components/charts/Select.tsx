import type { CSSProperties, ReactElement } from 'react'

export interface SelectOption<T extends string = string> {
    value: T
    label: string
}

export interface SelectProps<T extends string = string> {
    value: T
    onChange: (value: T) => void
    options: SelectOption<T>[]
    style?: CSSProperties
}

const defaultStyle: CSSProperties = {
    padding: '0.25rem 1.5rem 0.25rem 0.5rem',
    fontSize: '0.75rem',
    border: '1px solid var(--color-border-primary, #e5e7eb)',
    borderRadius: 'var(--border-radius-sm, 0.25rem)',
    backgroundColor: 'var(--color-background-primary, #fff)',
    color: 'var(--color-text-primary, #101828)',
    cursor: 'pointer',
}

export function Select<T extends string = string>({ value, onChange, options, style }: SelectProps<T>): ReactElement {
    return (
        <select value={value} onChange={(e) => onChange(e.target.value as T)} style={{ ...defaultStyle, ...style }}>
            {options.map((option) => (
                <option key={option.value} value={option.value}>
                    {option.label}
                </option>
            ))}
        </select>
    )
}
