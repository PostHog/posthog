import { AttachedContextChips } from './AttachedContextChips'
import { AttachedContextPicker } from './AttachedContextPicker'

export function AttachedContextBar(): JSX.Element | null {
    return <AttachedContextChips leading={<AttachedContextPicker />} />
}
