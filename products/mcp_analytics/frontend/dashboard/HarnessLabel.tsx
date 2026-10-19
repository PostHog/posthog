import { BrandMarkLabel } from '../components/BrandMarkLabel'
import { harnessMark } from './harnessRegistry'

export function HarnessLabel({ category }: { category: string }): JSX.Element {
    return <BrandMarkLabel label={category} mark={harnessMark(category)} />
}
