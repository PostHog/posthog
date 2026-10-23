import { markedNames, storyTextParts } from './storyMarks'

// A breakdown series is labelled `event - value`, with `::` between the values of several breakdowns.
// A value can hold ` - ` itself, so every part after one counts as a name.
function namesOf(label: string): string[] {
    const parts = label.split(' - ')
    const values = parts.map((_, index) => parts.slice(index).join(' - '))
    return [...values, ...values.flatMap((value) => value.split('::'))].map((name) => name.trim()).filter(Boolean)
}

function escapeRegExp(text: string): string {
    return text.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
}

export function isSeriesNamedIn(label: string, text: string): boolean {
    const marked = new Set(markedNames(text).map((name) => name.trim().toLowerCase()))
    const plain = storyTextParts(text)
        .map((part) => part.text)
        .join('')
    return namesOf(label).some(
        (name) =>
            marked.has(name.toLowerCase()) ||
            new RegExp(`(?<![\\p{L}\\p{N}])${escapeRegExp(name)}(?![\\p{L}\\p{N}])`, 'u').test(plain)
    )
}
