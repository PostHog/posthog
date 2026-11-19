// PROTOTYPE (branch prototype/sending-limits-ux): the floating variant switcher, never merge.
import { useEffect } from 'react'

import { IconChevronLeft, IconChevronRight } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

interface PrototypeSwitcherProps {
    variants: { key: string; label: string }[]
    current: string
    onChange: (key: string) => void
}

export function PrototypeSwitcher({ variants, current, onChange }: PrototypeSwitcherProps): JSX.Element {
    const index = Math.max(
        0,
        variants.findIndex((variant) => variant.key === current)
    )
    const step = (delta: number): void => onChange(variants[(index + delta + variants.length) % variants.length].key)

    useEffect(() => {
        const onKey = (event: KeyboardEvent): void => {
            const target = event.target as HTMLElement | null
            if (target?.closest('input, textarea, [contenteditable]')) {
                return
            }
            if (event.key === 'ArrowLeft') {
                step(-1)
            } else if (event.key === 'ArrowRight') {
                step(1)
            }
        }
        window.addEventListener('keydown', onKey)
        return () => window.removeEventListener('keydown', onKey)
    })

    return (
        <div className="fixed bottom-4 left-1/2 -translate-x-1/2 z-50 flex items-center gap-1 rounded-full bg-black text-white px-2 py-1 shadow-lg">
            <LemonButton size="small" icon={<IconChevronLeft className="text-white" />} onClick={() => step(-1)} />
            <span className="px-2 text-sm font-semibold whitespace-nowrap">{variants[index].label}</span>
            <LemonButton size="small" icon={<IconChevronRight className="text-white" />} onClick={() => step(1)} />
        </div>
    )
}
