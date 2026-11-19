export function ReplySuggestionHint({
    suggestion,
    acceptHint,
}: {
    suggestion: string
    acceptHint: JSX.Element
}): JSX.Element {
    const characters = Array.from(suggestion.trimEnd())
    const head = characters.slice(0, -1).join('')
    const lastCharacter = characters.slice(-1).join('')
    return (
        <span className="text-sm whitespace-pre-wrap break-words" data-attr="max-reply-suggestion">
            {head}
            <span className="whitespace-nowrap">
                {lastCharacter}
                <span className="ml-2 inline-flex align-middle">{acceptHint}</span>
            </span>
        </span>
    )
}
