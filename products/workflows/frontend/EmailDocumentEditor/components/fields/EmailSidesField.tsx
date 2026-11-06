import { useEffect, useState } from 'react'

import { LemonButton, LemonInput } from '@posthog/lemon-ui'

import { EmailSides } from '../../emailDocument'

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

    const side = (name: keyof EmailSides, title: string): JSX.Element => (
        <LemonInput
            type="number"
            size="small"
            min={0}
            aria-label={`${label} ${title}`}
            value={shown[name]}
            onChange={(next) => onChange({ ...shown, [name]: next ?? 0 })}
            data-attr={attr ? `${attr}-${name}` : undefined}
        />
    )

    return (
        <div className="flex flex-col gap-1">
            <div className="flex items-center gap-2 min-h-8">
                <span className="w-24 shrink-0 text-xs text-secondary">{label}</span>
                <div className="flex-1 min-w-0 flex items-center gap-1">
                    {expanded ? (
                        <span className="flex-1 text-xs text-secondary">Top, right, bottom, left</span>
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
                        <span className="text-xs px-0.5">{expanded ? '1' : '4'}</span>
                    </LemonButton>
                </div>
            </div>
            {expanded ? (
                <div className="grid grid-cols-4 gap-1">
                    {side('top', 'Top')}
                    {side('right', 'Right')}
                    {side('bottom', 'Bottom')}
                    {side('left', 'Left')}
                </div>
            ) : null}
        </div>
    )
}
