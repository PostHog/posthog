import { cn } from '@posthog/quill'

/** The quill sibling of `DiffBlock`: a unified diff, each line colored by its leading character. */
export function QuillDiffBlock({ diff }: { diff: string }): JSX.Element {
    const lines = diff.replace(/\n$/, '').split('\n')
    return (
        <pre className="m-0 max-h-96 overflow-auto rounded-md border border-border bg-card p-2 font-mono text-xxs leading-normal">
            {lines.map((line, i) => {
                const added = line.startsWith('+') && !line.startsWith('+++')
                const removed = line.startsWith('-') && !line.startsWith('---')
                const hunk = line.startsWith('@@')
                return (
                    <span
                        key={i}
                        className={cn(
                            'block whitespace-pre',
                            added && 'bg-success text-success-foreground',
                            removed && 'bg-destructive text-destructive-foreground',
                            hunk && 'text-subtle-foreground',
                            !added && !removed && !hunk && 'text-foreground'
                        )}
                    >
                        {line === '' ? ' ' : line}
                    </span>
                )
            })}
        </pre>
    )
}
