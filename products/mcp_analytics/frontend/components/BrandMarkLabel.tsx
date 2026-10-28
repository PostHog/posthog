import { BrandMark, toBrandMarkName } from './BrandMark'
import { CustomHarnessIcon } from './CustomHarnessIcon'

export function BrandMarkLabel({ label, mark }: { label: string; mark: string }): JSX.Element {
    const brandMark = toBrandMarkName(mark)
    return (
        <span className="inline-flex items-center gap-1.5" data-attr="hogqlx-brand-mark-label">
            {brandMark === 'Other harnesses' ? <CustomHarnessIcon harness={label} /> : <BrandMark name={brandMark} />}
            <span>{label}</span>
        </span>
    )
}
