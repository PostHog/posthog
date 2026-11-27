import './SourceFilterErrorLocation.scss'

import { cn } from 'lib/utils/css-classes'

import { SourceFilterErrorSpan, splitAtErrorSpan } from './sourceFilterErrorSpan'

export interface SourceFilterErrorLocationProps {
    expression: string
    span: SourceFilterErrorSpan
}

/** A read-only copy of the expression with its invalid part underlined. */
export function SourceFilterErrorLocation({ expression, span }: SourceFilterErrorLocationProps): JSX.Element {
    const { before, marked, after } = splitAtErrorSpan(expression, span)
    const isPoint = marked === ''

    // The expression is code, so translation stays off for it and on for the screen reader text.
    return (
        <pre
            translate="no"
            className="m-0 rounded border border-primary bg-surface-secondary px-2 py-1.5 font-mono text-xs whitespace-pre-wrap break-words"
        >
            <span>{before}</span>
            <span
                className={cn('SourceFilterErrorLocation__mark', isPoint && 'SourceFilterErrorLocation__mark--point')}
            >
                <span className="sr-only" translate="yes">
                    {isPoint ? 'The filter is invalid at this point.' : 'Invalid part starts.'}
                </span>
                {/* A point error has no text to underline, so a space holds the mark. */}
                <span>{isPoint ? '\u00a0' : marked}</span>
                {!isPoint && (
                    <span className="sr-only" translate="yes">
                        Invalid part ends.
                    </span>
                )}
            </span>
            <span>{after}</span>
        </pre>
    )
}
