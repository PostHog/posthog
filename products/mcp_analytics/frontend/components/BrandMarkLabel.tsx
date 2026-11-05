import { BrandMark, toBrandMarkName } from './BrandMark'

export function BrandMarkLabel({ label, mark }: { label: string; mark: string }): JSX.Element {
    return (
        <span className="inline-flex items-center gap-1.5" data-attr="hogqlx-brand-mark-label">
            <BrandMark name={toBrandMarkName(mark)} />
            <span>{label}</span>
        </span>
    )
}
