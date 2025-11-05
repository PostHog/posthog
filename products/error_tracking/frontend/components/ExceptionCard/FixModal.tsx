import { useActions, useValues } from 'kea'
import posthog from 'posthog-js'
import { useEffect } from 'react'

import { LemonButton, LemonModal } from '@posthog/lemon-ui'

import { errorPropertiesLogic } from 'lib/components/Errors/errorPropertiesLogic'
import { stackFrameLogic } from 'lib/components/Errors/stackFrameLogic'
import { ErrorTrackingException } from 'lib/components/Errors/types'
import { formatResolvedName, formatType } from 'lib/components/Errors/utils'
import { copyToClipboard } from 'lib/utils/copyToClipboard'

interface FixModalProps {
    isOpen: boolean
    onClose: () => void
}

export function FixModal({ isOpen, onClose }: FixModalProps): JSX.Element {
    const { exceptionList } = useValues(errorPropertiesLogic)
    const { stackFrameRecords } = useValues(stackFrameLogic)
    const { loadFromRawIds } = useActions(stackFrameLogic)

    // Load all raw_ids for frames when modal opens
    useEffect(() => {
        if (isOpen && exceptionList.length > 0) {
            const rawIds = exceptionList
                .flatMap((exception) => exception.stacktrace?.frames || [])
                .map((frame) => frame.raw_id)
            if (rawIds.length > 0) {
                loadFromRawIds(rawIds)
            }
        }
    }, [isOpen, exceptionList, loadFromRawIds])

    const generatePrompt = (): string => {
        const stacktraceText = exceptionList
            .map((exception) => generateExceptionText(exception, stackFrameRecords))
            .join('\n\n')

        return `Please help me fix this error. Here's the stack trace:

\`\`\`
${stacktraceText}
\`\`\`

Note: Frames marked with [IN-APP] are from the application code (my code), while frames without this marker are from external libraries/frameworks.
Focus your analysis primarily on the [IN-APP] frames as these are most likely where the issue needs to be fixed.

Can you:
1. Analyze what's causing this error. Try to consider multiple possible factors, and dig deep to find a root cause.
2. Explain in detail why this error occurred. Provide code examples if applicable.
3. Suggest the most likely fix, enumerating multiple possible solutions and choosing the best one.
4. Attempt to fix this error.

The final output of your efforts should be:
- An implemented fix for the issue
- A detailed explanation of the fix and how it addresses the root cause
`
    }

    const handleCopy = (): void => {
        void copyToClipboard(generatePrompt(), 'LLM prompt')
        posthog.capture('error_tracking_prompt_copied')
        onClose()
    }

    return (
        <LemonModal
            isOpen={isOpen}
            onClose={onClose}
            title="Fix this error with AI"
            width="50rem"
            footer={
                <div className="flex items-center justify-end gap-2">
                    <LemonButton type="secondary" onClick={onClose}>
                        Close
                    </LemonButton>
                    <LemonButton type="primary" onClick={handleCopy}>
                        Copy to clipboard
                    </LemonButton>
                </div>
            }
        >
            <div className="space-y-4">
                <p className="text-muted">
                    Paste this prompt into your favourite coding assistant to get help fixing this error:
                </p>
                <div className="bg-bg-light border rounded p-4 font-mono text-sm whitespace-pre-wrap max-h-96 overflow-auto">
                    {generatePrompt()}
                </div>
            </div>
        </LemonModal>
    )
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
