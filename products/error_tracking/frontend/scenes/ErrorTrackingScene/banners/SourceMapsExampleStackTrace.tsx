import { Badge } from 'lib/ui/quill'
import { cn } from 'lib/utils/css-classes'

import type { MissingSymbolsStackFrameApi } from '../../../generated/api.schemas'

function frameLocation(frame: MissingSymbolsStackFrameApi): string {
    const position = [frame.line, frame.column].filter((part) => part !== null).join(':')
    return [frame.source ?? 'Unknown file', position].filter(Boolean).join(':')
}

export function SourceMapsExampleStackTrace({
    frames,
    missingLabel,
}: {
    frames: MissingSymbolsStackFrameApi[]
    missingLabel: string
}): JSX.Element {
    return (
        // A stack trace is machine data, so page translators leave it alone.
        <div className="flex flex-col overflow-hidden rounded-md border border-border" translate="no">
            {frames.map((frame, index) => (
                <div
                    key={index}
                    className={cn(
                        'flex items-center gap-2 px-2 py-1 font-mono text-xs',
                        index > 0 && 'border-t border-border',
                        frame.missing_symbols ? 'bg-warning text-warning-foreground' : 'text-muted-foreground'
                    )}
                >
                    <span className={cn('shrink-0', frame.missing_symbols ? 'font-semibold' : 'text-foreground')}>
                        {frame.function ?? '?'}
                    </span>
                    <span className="min-w-0 truncate">{frameLocation(frame)}</span>
                    {frame.missing_symbols ? (
                        <Badge variant="warning" className="ml-auto shrink-0 font-sans">
                            No {missingLabel}
                        </Badge>
                    ) : null}
                </div>
            ))}
        </div>
    )
}
