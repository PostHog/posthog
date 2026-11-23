import type { AEOBrandSentimentSentenceApi } from '../generated/api.schemas'
import type { AnswerSegment } from './answerMentions'

export const SENTIMENT_LABELS: Record<string, string> = {
    positive: 'Positive',
    neutral: 'Neutral',
    negative: 'Negative',
}

/** A run of answer text: either one scored sentence, or the text between two scored sentences. */
export interface AnswerSentimentBlock {
    sentence: AEOBrandSentimentSentenceApi | null
    segments: AnswerSegment[]
}

// The API counts sentence offsets in Unicode code points and JavaScript indexes strings in UTF-16 units,
// so the two disagree after the first character outside the Basic Multilingual Plane, such as an emoji.
const utf16Offsets = (text: string): ((codePoints: number) => number) => {
    if (!/[\uD800-\uDBFF]/.test(text)) {
        return (codePoints) => Math.min(codePoints, text.length)
    }
    const starts: number[] = []
    for (let index = 0; index < text.length; index += (text.codePointAt(index) ?? 0) > 0xffff ? 2 : 1) {
        starts.push(index)
    }
    return (codePoints) => starts[codePoints] ?? text.length
}

/** Groups an answer's segments by scored sentence, cutting a segment where a sentence starts or ends.
 *  A sentence that is empty, out of order or overlaps the one before it is left out. */
export function answerSentimentBlocks(
    text: string,
    segments: AnswerSegment[],
    sentences: AEOBrandSentimentSentenceApi[]
): AnswerSentimentBlock[] {
    const toUtf16 = utf16Offsets(text)
    const ranges: { start: number; end: number; sentence: AEOBrandSentimentSentenceApi }[] = []
    for (const sentence of sentences) {
        const start = toUtf16(sentence.start)
        const end = toUtf16(sentence.end)
        if (start < end && start >= (ranges[ranges.length - 1]?.end ?? 0)) {
            ranges.push({ start, end, sentence })
        }
    }

    const blocks: AnswerSentimentBlock[] = []
    const push = (segment: AnswerSegment, sentence: AEOBrandSentimentSentenceApi | null): void => {
        const last = blocks[blocks.length - 1]
        if (last && last.sentence === sentence) {
            last.segments.push(segment)
        } else {
            blocks.push({ sentence, segments: [segment] })
        }
    }
    let offset = 0
    let rangeIndex = 0
    for (const segment of segments) {
        const segmentEnd = offset + segment.text.length
        while (offset < segmentEnd) {
            while (rangeIndex < ranges.length && ranges[rangeIndex].end <= offset) {
                rangeIndex++
            }
            const range = ranges[rangeIndex]
            const inside = range !== undefined && range.start <= offset
            const cut = Math.min(segmentEnd, inside ? range.end : (range?.start ?? segmentEnd))
            const start = offset - (segmentEnd - segment.text.length)
            push({ ...segment, text: segment.text.slice(start, start + cut - offset) }, inside ? range.sentence : null)
            offset = cut
        }
    }
    return blocks
}
