export interface SourceFilterErrorSpan {
    /** 0-based code point offset where the invalid part starts. */
    start: number
    /** Offset just after the invalid part. Equal to `start` when the error is at one point. */
    end: number
}

export interface SourceFilterErrorSpanParts {
    before: string
    marked: string
    after: string
}

/** Clamps the offsets to the text, so a span that runs past the end marks only what is there. */
export function splitAtErrorSpan(text: string, { start, end }: SourceFilterErrorSpan): SourceFilterErrorSpanParts {
    const codePoints = Array.from(text)
    const from = Math.min(Math.max(start, 0), codePoints.length)
    const to = Math.min(Math.max(end, from), codePoints.length)
    return {
        before: codePoints.slice(0, from).join(''),
        marked: codePoints.slice(from, to).join(''),
        after: codePoints.slice(to).join(''),
    }
}
