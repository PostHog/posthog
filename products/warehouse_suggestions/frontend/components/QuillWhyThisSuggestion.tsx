import { daysReadLabel, surfaceSegments } from '../suggestionCopy'
import { QuillHintedText } from './QuillHintedText'
import { ReadsBySurfaceBar } from './ReadsBySurfaceBar'
import { WhyThisSuggestionProps } from './WhyThisSuggestion'

export function QuillWhyThisSuggestion({ evidence, windowDays, label }: WhyThisSuggestionProps): JSX.Element {
    const segments = surfaceSegments(evidence)
    const daysRead = (evidence.human_days ?? 0) > 0 ? daysReadLabel(evidence, windowDays) : null

    if (segments.length === 0 && !daysRead) {
        return <span translate="no">{label}</span>
    }

    return (
        <QuillHintedText
            label={label}
            hint={
                <div className="flex w-64 max-w-full flex-col gap-2 py-0.5">
                    {segments.length > 0 && <ReadsBySurfaceBar segments={segments} />}
                    {daysRead && <span>{daysRead}</span>}
                </div>
            }
            hintText={[segments.map((segment) => `${segment.label} ${segment.count}`).join(', '), daysRead]
                .filter(Boolean)
                .map((part) => `. ${part}`)
                .join('')}
            dataAttr="warehouse-suggestions-why-this"
        />
    )
}
