export function ReplySuggestionHint({
    suggestion,
    acceptHint,
}: {
    suggestion: string
    acceptHint: JSX.Element
}): JSX.Element {
    const trimmed = suggestion.trimEnd()
    const lastWordStart = trimmed.search(/\S+$/)
    const head = lastWordStart > 0 ? trimmed.slice(0, lastWordStart) : ''
    const lastWord = lastWordStart > 0 ? trimmed.slice(lastWordStart) : trimmed
    return (
        <span className="text-sm whitespace-pre-wrap break-words" data-attr="max-reply-suggestion">
            {head}
            <span className="whitespace-nowrap">
                {lastWord}
                <span className="ml-2 inline-flex align-middle">{acceptHint}</span>
            </span>
        </span>
    )
}
