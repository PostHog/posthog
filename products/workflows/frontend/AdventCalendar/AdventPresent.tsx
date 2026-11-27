import { cn } from 'lib/utils/css-classes'

export function AdventPresent({ className }: { className?: string }): JSX.Element {
    return (
        <svg viewBox="0 0 64 64" className={cn('AdventPresent', className)} overflow="visible" aria-hidden>
            <g>
                <rect x="10" y="29" width="44" height="32" rx="2.5" fill="var(--advent-red)" />
                <rect x="28" y="29" width="8" height="32" fill="var(--advent-gold)" />
                <rect x="10" y="29" width="44" height="3" fill="var(--advent-ink)" opacity="0.18" />
            </g>
            <g>
                <rect x="7" y="19" width="50" height="11" rx="2.5" fill="var(--advent-red)" />
                <rect x="28" y="19" width="8" height="11" fill="var(--advent-gold)" />
                <path d="M32 19 C 22 3, 8 10, 20 19 Z" fill="var(--advent-gold)" />
                <path d="M32 19 C 42 3, 56 10, 44 19 Z" fill="var(--advent-gold)" />
                <circle cx="32" cy="18.5" r="3.4" fill="var(--advent-ember)" />
            </g>
        </svg>
    )
}
