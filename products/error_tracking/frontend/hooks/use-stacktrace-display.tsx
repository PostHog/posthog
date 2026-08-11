import { useValues } from 'kea'
import { useMemo } from 'react'

import { toDisplayOrderFrames } from 'lib/components/Errors/displayOrder'
import { errorPropertiesLogic } from 'lib/components/Errors/errorPropertiesLogic'
import { ErrorTrackingException } from 'lib/components/Errors/types'
import { formatResolvedName, formatType } from 'lib/components/Errors/utils'

export const useStacktraceDisplay = (): { ready: boolean; stacktraceText: string; copyableStacktraceText: string } => {
    const { exceptionList, stackFrameRecords, stackFrameRecordsLoading, framesStoredCrashFirst } =
        useValues(errorPropertiesLogic)

    const stacktraceText = useMemo(() => {
        return exceptionList
            .map((exception) =>
                generateExceptionText(exception, stackFrameRecords, {
                    includeInAppMarkers: true,
                    storedCrashFirst: framesStoredCrashFirst,
                })
            )
            .join('\n\n')
    }, [exceptionList, stackFrameRecords, framesStoredCrashFirst])

    const copyableStacktraceText = useMemo(() => {
        return exceptionList
            .map((exception) =>
                generateExceptionText(exception, stackFrameRecords, {
                    includeInAppMarkers: false,
                    storedCrashFirst: framesStoredCrashFirst,
                })
            )
            .join('\n\n')
    }, [exceptionList, stackFrameRecords, framesStoredCrashFirst])

    const ready = exceptionList.length > 0 && !stackFrameRecordsLoading

    return { ready, stacktraceText, copyableStacktraceText }
}

function generateExceptionText(
    exception: ErrorTrackingException,
    stackFrameRecords: Record<string, any>,
    options: { includeInAppMarkers: boolean; storedCrashFirst: boolean }
): string {
    let result = `${formatType(exception)}${exception.value ? `: ${exception.value}` : ''}`

    // match the on-screen order: most recent call first
    const frames = toDisplayOrderFrames(exception.stacktrace?.frames || [], options.storedCrashFirst)

    for (const frame of frames) {
        const inAppMarker = options.includeInAppMarkers && frame.in_app ? ' [IN-APP]' : ''
        const resolvedName = formatResolvedName(frame)
        result += `\n${inAppMarker}  File "${frame.source || 'Unknown Source'}"${frame.line ? `, line: ${frame.line}` : ''}${resolvedName ? `, in: ${resolvedName}` : ''}`

        const frameRecord = stackFrameRecords[frame.raw_id]
        if (frameRecord?.context?.line?.line) {
            result += `\n    ${frameRecord.context.line.line}`
        }
    }

    return result
}
