import { MessageSegment, MessageSegmentKind } from './suppressSimilarScopes'

const PLACEHOLDER_LABELS: Record<Exclude<MessageSegmentKind, 'literal'>, string> = {
    number: 'number',
    id: 'ID',
    hex: 'hash',
}

// It uses app surface tokens, because the web app's own `--muted` overrides quill's inside the dialog portal.
export function MessagePattern({ segments }: { segments: MessageSegment[] }): JSX.Element {
    return (
        <code className="w-fit rounded-sm border border-primary bg-surface-secondary px-1 font-mono text-xs break-all">
            {segments.map((segment, index) =>
                segment.kind === 'literal' ? (
                    <span key={index}>{segment.text}</span>
                ) : (
                    <span
                        key={index}
                        className="mx-px rounded-xs bg-accent-highlight-secondary px-0.5 font-sans text-xxs text-accent"
                    >
                        {PLACEHOLDER_LABELS[segment.kind]}
                    </span>
                )
            )}
        </code>
    )
}
