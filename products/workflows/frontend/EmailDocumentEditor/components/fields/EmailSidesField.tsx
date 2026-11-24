import { useState } from 'react'

import { LemonInput, LemonSegmentedButton } from '@posthog/lemon-ui'

import { EmailSides } from '../../emailDocument'
import { numberOrUnset } from './numberOrUnset'

const SIDES: { name: keyof EmailSides; title: string }[] = [
    { name: 'top', title: 'Top' },
    { name: 'right', title: 'Right' },
    { name: 'bottom', title: 'Bottom' },
    { name: 'left', title: 'Left' },
]

const MODE_TITLES = { same: 'Same on all sides', each: 'Set each side' }

function IconSameSides(): JSX.Element {
    return (
        <svg width="14" height="14" viewBox="0 0 14 14" fill="none" stroke="currentColor" strokeWidth="1.5" aria-hidden>
            <rect x="1.5" y="1.5" width="11" height="11" rx="1" />
        </svg>
    )
}

function IconEachSide(): JSX.Element {
    return (
        <svg width="14" height="14" viewBox="0 0 14 14" fill="none" stroke="currentColor" strokeWidth="1.5" aria-hidden>
            <path d="M4 1.5h6M4 12.5h6M1.5 4v6M12.5 4v6" strokeLinecap="round" />
        </svg>
    )
}

export function EmailSidesField({
    label,
    value,
    placeholder,
    onChange,
    attr,
}: {
    label: string
    value: EmailSides | undefined
    placeholder: EmailSides
    onChange: (value: EmailSides | undefined) => void
    attr?: string
}): JSX.Element {
    const shown = value ?? placeholder
    const uneven = shown.top !== shown.right || shown.top !== shown.bottom || shown.top !== shown.left
    // Opened by a person, so sides that become equal while they are edited stay open.
    const [opened, setOpened] = useState(false)
    const mode = opened || uneven ? 'each' : 'same'

    return (
        <div className="flex flex-col gap-1">
            <div className="flex items-center gap-2 min-h-8">
                <span className="w-24 shrink-0 text-xs text-secondary">{label}</span>
                <div className="flex-1 min-w-0 flex items-center gap-1">
                    {mode === 'each' ? (
                        <div className="flex-1" />
                    ) : (
                        <LemonInput
                            type="number"
                            size="small"
                            fullWidth
                            min={0}
                            aria-label={label}
                            value={shown.top}
                            suffix={<span className="text-xs text-secondary">px</span>}
                            onChange={(next) => {
                                const all = numberOrUnset(next) ?? 0
                                onChange({ top: all, right: all, bottom: all, left: all })
                            }}
                            data-attr={attr}
                        />
                    )}
                    {/* LemonSegmentedButton shows which option is selected only visually. */}
                    <div role="group" aria-label={`${label}: ${MODE_TITLES[mode]}`}>
                        <LemonSegmentedButton
                            size="xsmall"
                            value={mode}
                            onChange={(next) => {
                                if (next === mode) {
                                    return
                                }
                                setOpened(next === 'each')
                                if (next === 'same' && uneven) {
                                    onChange({ top: shown.top, right: shown.top, bottom: shown.top, left: shown.top })
                                }
                            }}
                            options={[
                                {
                                    value: 'same',
                                    icon: <IconSameSides />,
                                    tooltip: MODE_TITLES.same,
                                    'data-attr': attr ? `${attr}-same` : undefined,
                                },
                                {
                                    value: 'each',
                                    icon: <IconEachSide />,
                                    tooltip: MODE_TITLES.each,
                                    'data-attr': attr ? `${attr}-each` : undefined,
                                },
                            ]}
                        />
                    </div>
                </div>
            </div>
            {mode === 'each' ? (
                <div className="grid grid-cols-4 gap-1">
                    {SIDES.map(({ name, title }) => (
                        <label key={name} className="flex flex-col gap-0.5 text-xxs text-secondary">
                            <LemonInput
                                type="number"
                                size="small"
                                min={0}
                                aria-label={`${label} ${title}`}
                                value={shown[name]}
                                onChange={(next) => {
                                    setOpened(true)
                                    onChange({ ...shown, [name]: numberOrUnset(next) ?? 0 })
                                }}
                                data-attr={attr ? `${attr}-${name}` : undefined}
                            />
                            {title}
                        </label>
                    ))}
                </div>
            ) : null}
        </div>
    )
}
