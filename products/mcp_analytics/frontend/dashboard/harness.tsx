import { harnessLogo } from './harnessRegistry'

// A single harness logo (or a neutral dot when no logo is known for the category).
export function HarnessLogo({
    category,
    className = 'h-4 w-4',
}: {
    category: string
    className?: string
}): JSX.Element {
    const logo = harnessLogo(category)
    if (logo) {
        return <img src={logo.src} alt={category} title={category} className={`${className} shrink-0 object-contain`} />
    }
    return <span title={category} className="inline-block h-1.5 w-1.5 shrink-0 rounded-full bg-secondary" aria-hidden />
}

export function HarnessPill({ category, title }: { category: string; title?: string }): JSX.Element {
    return (
        <span
            className="inline-flex max-w-full items-center gap-1.5 rounded-full border border-primary bg-surface-primary px-2 py-0.5 text-xs"
            title={title}
        >
            <HarnessLogo category={category} className="h-3.5 w-3.5" />
            <span className="truncate">{category}</span>
        </span>
    )
}
