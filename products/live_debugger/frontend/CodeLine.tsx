import clsx from 'clsx'

import { highlightPythonSyntax } from './codeUtils'

export function CodeLine({
    line,
    lineNumber,
    hasBreakpoint,
    hasInstances,
    hitCount,
    hasNewHits,
    onClick,
    onHitCountClick,
}: {
    line: string
    lineNumber: number
    hasBreakpoint: boolean
    hasInstances: boolean
    hitCount: number
    hasNewHits: boolean
    onClick: () => void
    onHitCountClick: () => void
}): JSX.Element {
    return (
        <div
            className={clsx(
                'flex items-center group hover:bg-bg-3000 transition-colors',
                hasNewHits && 'bg-yellow-100 dark:bg-yellow-900/20'
            )}
        >
            <div className="flex items-center justify-center w-10 px-1 cursor-pointer select-none" onClick={onClick}>
                <div className="relative flex items-center justify-center">
                    {hasBreakpoint ? (
                        hasInstances ? (
                            <div className="w-3 h-3 bg-warning rounded-full animate-pulse border-2 border-danger" />
                        ) : (
                            <div className="w-3 h-3 bg-danger rounded-full" />
                        )
                    ) : hasInstances ? (
                        <div className="w-3 h-3 bg-warning rounded-full animate-pulse" />
                    ) : (
                        <div className="w-3 h-3 border border-muted rounded-full opacity-0 group-hover:opacity-100 transition-opacity" />
                    )}
                </div>
            </div>
            <div className="w-10 text-right pr-2 text-muted text-xs select-none">{lineNumber}</div>
            {hitCount > 0 && (
                <div
                    className="w-6 h-4 text-xs bg-orange-500 text-white rounded-full flex items-center justify-center cursor-pointer mr-2 hover:bg-orange-600 transition-colors"
                    onClick={onHitCountClick}
                    title={`${hitCount} breakpoint hit${hitCount > 1 ? 's' : ''}`}
                >
                    {hitCount}
                </div>
            )}
            <pre className="flex-1 m-0 text-xs overflow-hidden whitespace-pre">
                <code className="block" dangerouslySetInnerHTML={{ __html: highlightPythonSyntax(line || ' ') }} />
            </pre>
        </div>
    )
}
