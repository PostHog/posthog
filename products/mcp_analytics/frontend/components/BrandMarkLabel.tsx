import { BrandMark, toBrandMarkName } from './BrandMark'

export function BrandMarkLabel({
    label,
    mark,
    icon,
}: {
    label: string
    mark: string
    icon?: JSX.Element
}): JSX.Element {
    return (
        <span className="inline-flex items-center gap-1.5" data-attr="hogqlx-brand-mark-label">
            {icon ?? <BrandMark name={toBrandMarkName(mark)} />}
            <span>{label}</span>
        </span>
    )
}
