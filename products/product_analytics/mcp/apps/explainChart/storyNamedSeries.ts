import { markedNames, storyTextParts } from './storyMarks'

function escapeRegExp(text: string): string {
    return text.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
}

export function isSeriesNamedIn(names: string[], text: string): boolean {
    const marked = new Set(markedNames(text).map((name) => name.trim().toLowerCase()))
    const plain = storyTextParts(text)
        .map((part) => part.text)
        .join('')
    return names
        .map((name) => name.trim())
        .filter(Boolean)
        .some(
            (name) =>
                marked.has(name.toLowerCase()) ||
                new RegExp(`(?<![\\p{L}\\p{N}_])${escapeRegExp(name)}(?![\\p{L}\\p{N}_])`, 'u').test(plain)
        )
}
