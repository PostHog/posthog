import { useValues } from 'kea'
import { useMemo } from 'react'

import { errorPropertiesLogic } from 'lib/components/Errors/errorPropertiesLogic'
import { stackFrameLogic } from 'lib/components/Errors/stackFrameLogic'
import { ErrorTrackingException } from 'lib/components/Errors/types'
import { formatResolvedName, formatType } from 'lib/components/Errors/utils'

export const useStacktraceDisplay = (): { ready: boolean; stacktraceText: string } => {
    const { exceptionList } = useValues(errorPropertiesLogic)
    const { stackFrameRecords } = useValues(stackFrameLogic)

    const stacktraceText = useMemo(() => {
        return exceptionList.map((exception) => generateExceptionText(exception, stackFrameRecords)).join('\n\n')
    }, [exceptionList, stackFrameRecords])

    const ready = exceptionList.length > 0 && Object.keys(stackFrameRecords).length > 0

    return { ready, stacktraceText }
}

function generateExceptionText(exception: ErrorTrackingException, stackFrameRecords: Record<string, any>): string {
    let result = `${formatType(exception)}: ${exception.value}`

    const frames = exception.stacktrace?.frames || []

    for (const frame of frames) {
        const inAppMarker = frame.in_app ? ' [IN-APP]' : ''
        const resolvedName = formatResolvedName(frame)
        result += `\n${inAppMarker}  File "${frame.source || 'Unknown Source'}"${frame.line ? `, line: ${frame.line}` : ''}${resolvedName ? `, in: ${resolvedName}` : ''}`

        const frameRecord = stackFrameRecords[frame.raw_id]
        if (frameRecord?.context?.line?.line) {
            result += `\n    ${frameRecord.context.line.line}`
        }
    }

    return result
}
