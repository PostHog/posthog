import { useValues } from 'kea'
import { useMemo } from 'react'

import { errorPropertiesLogic } from 'lib/components/Errors/errorPropertiesLogic'
import { ErrorTrackingException } from 'lib/components/Errors/types'
import { formatResolvedName, formatType } from 'lib/components/Errors/utils'

export const useStacktraceDisplay = (): { ready: boolean; stacktraceText: string; copyableStacktraceText: string } => {
    const { exceptionList, stackFrameRecords, stackFrameRecordsLoading } = useValues(errorPropertiesLogic)

    const stacktraceText = useMemo(() => {
        return exceptionList
            .map((exception) => generateExceptionText(exception, stackFrameRecords, { includeInAppMarkers: true }))
            .join('\n\n')
    }, [exceptionList, stackFrameRecords])

    const copyableStacktraceText = useMemo(() => {
        return exceptionList
            .map((exception) => generateExceptionText(exception, stackFrameRecords, { includeInAppMarkers: false }))
            .join('\n\n')
    }, [exceptionList, stackFrameRecords])

    const ready = exceptionList.length > 0 && !stackFrameRecordsLoading

    return { ready, stacktraceText, copyableStacktraceText }
}

function generateExceptionText(
    exception: ErrorTrackingException,
    stackFrameRecords: Record<string, any>,
    options: { includeInAppMarkers: boolean }
): string {
    let result = `${formatType(exception)}${exception.value ? `: ${exception.value}` : ''}`

    const frames = exception.stacktrace?.frames || []

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
