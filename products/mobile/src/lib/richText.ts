export interface TextSegment {
    text: string
    bold: boolean
}

/** Splits "a **b** c" into plain and bold segments. Unpaired markers stay plain. */
export function parseBold(input: string): TextSegment[] {
    const parts = input.split('**')
    if (parts.length % 2 === 0) {
        return [{ text: input, bold: false }]
    }
    return parts.map((text, index) => ({ text, bold: index % 2 === 1 })).filter((segment) => segment.text !== '')
}
