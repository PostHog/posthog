import { BrandMark } from '../components/BrandMark'
import { harnessMark } from './harnessRegistry'

export function HarnessLogo({
    category,
    className = 'h-4 w-4',
}: {
    category: string
    className?: string
}): JSX.Element {
    return <BrandMark name={harnessMark(category)} className={className} />
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
