import { cn } from 'lib/utils/css-classes'

export function AdventTicketIcon({ className }: { className?: string }): JSX.Element {
    return (
        <svg viewBox="-1 -1 36 22" className={cn('AdventTicketIcon', className)} aria-hidden>
            <path
                d="M0 2a2 2 0 0 1 2-2h30a2 2 0 0 1 2 2v5a3.5 3.5 0 0 0 0 7v4a2 2 0 0 1-2 2H2a2 2 0 0 1-2-2v-4a3.5 3.5 0 0 0 0-7Z"
                fill="var(--advent-paper)"
                stroke="var(--advent-gold)"
                strokeWidth="1.6"
            />
            <path d="M10 3v14" stroke="var(--advent-gold)" strokeWidth="1.2" strokeDasharray="1.6 1.6" />
        </svg>
    )
}
