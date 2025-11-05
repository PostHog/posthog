import { useActions, useValues } from 'kea'
import { useEffect } from 'react'

import { LemonSkeleton } from '@posthog/lemon-ui'

import { errorPropertiesLogic } from 'lib/components/Errors/errorPropertiesLogic'
import { stackFrameLogic } from 'lib/components/Errors/stackFrameLogic'
import { ErrorTrackingException, ErrorTrackingStackFrame } from 'lib/components/Errors/types'
import { formatExceptionDisplay, formatResolvedName } from 'lib/components/Errors/utils'

import { exceptionCardLogic } from '../exceptionCardLogic'
import { StacktraceBaseDisplayProps } from './StacktraceBase'

export function StacktraceTextDisplay({ className, renderEmpty }: StacktraceBaseDisplayProps): JSX.Element {
    const { exceptionList, hasStacktrace } = useValues(errorPropertiesLogic)
    const { loading } = useValues(exceptionCardLogic)
    return (
        <div className={className}>
            {loading ? (
                <LemonSkeleton className="h-2 w-1/2" />
            ) : (
                exceptionList.map((exception: ErrorTrackingException) => (
                    <ExceptionTextDisplay key={exception.id} exception={exception} />
                ))
            )}
            {!loading && !hasStacktrace && renderEmpty()}
        </div>
    )
}

function ExceptionTextDisplay({ exception }: { exception: ErrorTrackingException }): JSX.Element {
    const { showAllFrames } = useValues(exceptionCardLogic)
    return (
        <div>
            <p className="font-mono mb-0 font-bold line-clamp-1">{formatExceptionDisplay(exception)}</p>
            {(exception.stacktrace?.frames || [])
                .filter((frame: ErrorTrackingStackFrame) => (showAllFrames ? true : frame.in_app))
                .map((frame, idx) => (
                    <StackframeTextDisplay key={idx} frame={frame} />
                ))}
        </div>
    )
}

function StackframeTextDisplay({ frame }: { frame: ErrorTrackingStackFrame }): JSX.Element {
    const { stackFrameRecords } = useValues(stackFrameLogic)
    const { loadFromRawIds } = useActions(stackFrameLogic)
    useEffect(() => {
        loadFromRawIds([frame.raw_id])
    }, [loadFromRawIds, frame.raw_id])
    const resolvedName = formatResolvedName(frame)
    return (
        <>
            <p className="font-mono indent-[1rem] whitespace-no-wrap mb-0 line-clamp-1">
                File "{frame.source || 'Unknown Source'}"{frame.line ? `, line: ${frame.line}` : ''}
                {resolvedName ? `, in: ${resolvedName}` : ''}
            </p>
            {stackFrameRecords[frame.raw_id] && stackFrameRecords[frame.raw_id].context?.line.line && (
                <p className="font-mono indent-[2rem] whitespace-no-wrap mb-0 text-tertiary line-clamp-1">
                    {stackFrameRecords[frame.raw_id].context?.line.line}
                </p>
            )}
        </>
    )
}
