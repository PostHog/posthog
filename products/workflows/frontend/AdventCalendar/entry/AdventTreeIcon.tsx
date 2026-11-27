export function AdventTreeIcon({ className }: { className?: string }): JSX.Element {
    return (
        <svg viewBox="0 0 16 16" className={className} aria-hidden>
            <path d="M8 1 4.5 5.5h2L3.5 9.5h2.5L3 13.5h10L10 9.5h2.5l-3-4h2Z" fill="currentColor" />
            <rect x="7" y="13.5" width="2" height="1.5" rx="0.3" className="fill-warning" />
            <circle cx="8" cy="1.6" r="1.1" className="fill-warning" />
        </svg>
    )
}
