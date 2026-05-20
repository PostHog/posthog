import type { CSSProperties, ReactElement } from 'react'

// TODO(quill): consider migrating to Quill's `Select` primitive (composed
// `<Select>` + `<SelectTrigger>` + `<SelectContent>` + `<SelectItem>`).
// Kept as a native `<select>` for now because:
//   - Bundles inside an MCP UI app loaded as a sandboxed iframe in the
//     host. Floating UI portals (used by Quill's Select for popover
//     positioning) need careful handling inside iframes — the trigger and
//     content may render in different stacking contexts.
//   - Native `<select>` plays better with iOS/Android system pickers
//     when MCP apps are surfaced in mobile hosts.
// The styling already uses Quill tokens (`rounded-sm`, `border-input`,
// `bg-background`, `text-foreground`) so a future migration is JSX-only.

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

export function Select<T extends string = string>({ value, onChange, options, style }: SelectProps<T>): ReactElement {
    return (
        <select
            value={value}
            onChange={(e) => onChange(e.target.value as T)}
            className="cursor-pointer rounded-sm border border-input bg-background py-1 pl-2 pr-6 text-xs text-foreground"
            style={style}
        >
            {options.map((option) => (
                <option key={option.value} value={option.value}>
                    {option.label}
                </option>
            ))}
        </select>
    )
}
