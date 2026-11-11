import { BrandMarkLabel } from '../components/BrandMarkLabel'
import { CustomHarnessIcon } from '../components/CustomHarnessIcon'
import { harnessMark } from './harnessRegistry'

export function HarnessLabel({ category }: { category: string }): JSX.Element {
    const mark = harnessMark(category)
    return (
        <BrandMarkLabel
            label={category}
            mark={mark}
            icon={mark === 'Other harnesses' ? <CustomHarnessIcon harness={category} /> : undefined}
        />
    )
}
