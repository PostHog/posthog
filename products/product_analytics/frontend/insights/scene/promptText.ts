// A name is whatever an SDK or a person sent, so it must not be able to add lines of its own to a prompt.
export function quotedOneLine(text: string, maxLength: number = 80): string {
    const oneLine = Array.from(text, (character) => (character < ' ' || character === '\u007f' ? ' ' : character))
        .join('')
        .trim()
    return JSON.stringify(oneLine.slice(0, maxLength))
}
