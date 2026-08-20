import './DemoDiffBlock.scss'

import { cn } from 'lib/utils/css-classes'

export interface DemoDiffLine {
    text: string
    kind?: 'add' | 'remove' | 'meta'
}

/** Parse a unified-diff-ish snippet: lines starting with + are adds, - are removes. */
export function diffLinesFromSnippet(snippet: string): DemoDiffLine[] {
    return snippet.split('\n').map((text) => ({
        text,
        kind: text.startsWith('+') ? 'add' : text.startsWith('-') ? 'remove' : undefined,
    }))
}

/**
 * Dark code block with diff-style added/removed line highlighting, for the mock
 * commit diffs in the demo report pages. Dark in both themes, like CodeSnippet.
 */
export function DemoDiffBlock({
    title,
    lines,
    className,
}: {
    title?: string
    lines: DemoDiffLine[]
    className?: string
}): JSX.Element {
    return (
        <pre
            className={cn(
                'DemoDiffBlock m-0 overflow-x-auto rounded bg-surface-tooltip p-4 font-mono text-xs leading-6 text-primary-inverse',
                className
            )}
        >
            {title ? <span className="DemoDiffBlock__line--meta block">{title}</span> : null}
            {lines.map((line, index) => (
                <span
                    key={index}
                    className={cn('block whitespace-pre', line.kind && `DemoDiffBlock__line--${line.kind}`)}
                >
                    {line.text}
                </span>
            ))}
        </pre>
    )
}
