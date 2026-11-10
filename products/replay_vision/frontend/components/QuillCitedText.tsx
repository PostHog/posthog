import { parseCitedSegments } from '../utils/citations'
import { QuillTimestampCitation } from './QuillTimestampCitation'

export function QuillCitedText({
    text,
    segments,
    onSeek,
}: {
    text: string
    segments: unknown
    onSeek?: (timestampMs: number) => void
}): JSX.Element {
    const list = parseCitedSegments(text, segments)
    if (list.length === 0) {
        return <>{text}</>
    }
    return (
        <>
            {list.map((segment, i) =>
                segment.kind === 'text' ? (
                    <span key={i}>{segment.value}</span>
                ) : (
                    <QuillTimestampCitation key={i} timestampMs={segment.timestamp_ms} onSeek={onSeek} />
                )
            )}
        </>
    )
}
