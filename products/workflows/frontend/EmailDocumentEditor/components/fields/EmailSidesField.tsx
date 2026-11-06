import { useEffect, useState } from 'react'

import { LemonButton, LemonInput } from '@posthog/lemon-ui'

import { EmailSides } from '../../emailDocument'

const SIDES: { name: keyof EmailSides; title: string }[] = [
    { name: 'top', title: 'Top' },
    { name: 'right', title: 'Right' },
    { name: 'bottom', title: 'Bottom' },
    { name: 'left', title: 'Left' },
]

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
    const [expanded, setExpanded] = useState(uneven)
    useEffect(() => {
        if (uneven) {
            setExpanded(true)
        }
    }, [uneven])

    return (
        <div className="flex flex-col gap-1">
            <div className="flex items-center gap-2 min-h-8">
                <span className="w-24 shrink-0 text-xs text-secondary">{label}</span>
                <div className="flex-1 min-w-0 flex items-center gap-1">
                    {expanded ? (
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
                                const all = next ?? 0
                                onChange({ top: all, right: all, bottom: all, left: all })
                            }}
                            data-attr={attr}
                        />
                    )}
                    <LemonButton
                        size="xsmall"
                        noPadding
                        center
                        className="EmailEditor__square-button EmailEditor__square-button--compact"
                        active={expanded}
                        tooltip={expanded ? 'Same on all sides' : 'Set each side'}
                        aria-label={expanded ? 'Same on all sides' : 'Set each side'}
                        onClick={() => {
                            if (expanded) {
                                onChange({ top: shown.top, right: shown.top, bottom: shown.top, left: shown.top })
                            }
                            setExpanded(!expanded)
                        }}
                        data-attr={attr ? `${attr}-toggle` : undefined}
                    >
                        <IconEachSide />
                    </LemonButton>
                </div>
            </div>
            {expanded ? (
                <div className="grid grid-cols-4 gap-1">
                    {SIDES.map(({ name, title }) => (
                        <label key={name} className="flex flex-col gap-0.5 text-xxs text-secondary">
                            <LemonInput
                                type="number"
                                size="small"
                                min={0}
                                aria-label={`${label} ${title}`}
                                value={shown[name]}
                                onChange={(next) => onChange({ ...shown, [name]: next ?? 0 })}
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
