import type { DataAgeLabel } from '../suggestionCopy'
import { QuillHintedText } from './QuillHintedText'

export function QuillDataAgeMeta({ age }: { age: DataAgeLabel }): JSX.Element {
    if (!age.caveat) {
        return <span translate="no">{age.label}</span>
    }
    return <QuillHintedText label={age.label} hint={age.caveat} hintText={`. ${age.caveat}`} />
}
