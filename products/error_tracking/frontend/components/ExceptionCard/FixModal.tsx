import { useActions, useValues } from 'kea'
import posthog from 'posthog-js'

import { LemonButton, LemonModal, LemonSegmentedButton } from '@posthog/lemon-ui'

import { errorPropertiesLogic } from 'lib/components/Errors/errorPropertiesLogic'
import { stackFrameLogic } from 'lib/components/Errors/stackFrameLogic'
import { ErrorTrackingException } from 'lib/components/Errors/types'
import { formatResolvedName, formatType } from 'lib/components/Errors/utils'
import { copyToClipboard } from 'lib/utils/copyToClipboard'

import { fixModalLogic } from './fixModalLogic'

interface FixModalProps {
    isOpen: boolean
    onClose: () => void
}

export function FixModal({ isOpen, onClose }: FixModalProps): JSX.Element {
    const { exceptionList } = useValues(errorPropertiesLogic)
    const { stackFrameRecords } = useValues(stackFrameLogic)
    const { mode } = useValues(fixModalLogic)
    const { setMode } = useActions(fixModalLogic)

    const generatePrompt = (): string => {
        const stacktraceText = exceptionList
            .map((exception) => generateExceptionText(exception, stackFrameRecords))
            .join('\n\n')

        if (mode === 'explain') {
            return `Please help me understand this error in depth. Here's the stack trace:

\`\`\`
${stacktraceText}
\`\`\`

Note: Frames marked with [IN-APP] are from the application code (my code), while frames without this marker are from external libraries/frameworks.
Focus your analysis primarily on the [IN-APP] frames as these are most likely where the issue originates.

Can you:
1. Perform a deep dive analysis into what's causing this error. Consider multiple possible factors and dig deep to find the root cause.
2. Explain the relevant parts of the code that are involved in this error. Walk through the execution flow that leads to this issue.
3. Provide a detailed explanation of exactly how this issue happened, including the sequence of events and conditions that trigger it.
4. Include code examples and context where helpful to illustrate your explanation.

The final output should be:
- A comprehensive technical explanation of the root cause
- A walkthrough of the relevant code paths
- A detailed summary of exactly how the issue occurs
`
        }
        return `Please help me fix this error. Here's the stack trace:

\`\`\`
${stacktraceText}
\`\`\`

Note: Frames marked with [IN-APP] are from the application code (my code), while frames without this marker are from external libraries/frameworks.
Focus your analysis primarily on the [IN-APP] frames as these are most likely where the issue needs to be fixed.

Can you:
1. Gather relevant information from the codebase to understand the context of this error.
2. Inspect the code paths involved to identify the root cause.
3. Determine the simplest and cleanest fix for this issue.
4. Implement the fix directly in the codebase.

The final output of your efforts should be:
- An implemented fix for the issue applied directly to the code
- A brief explanation of what was changed and why
`
    }

    const handleCopy = (): void => {
        void copyToClipboard(generatePrompt(), 'LLM prompt')
        posthog.capture('error_tracking_prompt_copied', { mode })
        onClose()
    }

    return (
        <LemonModal
            isOpen={isOpen}
            onClose={onClose}
            title={mode === 'explain' ? 'Explain this error with AI' : 'Fix this error with AI'}
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
                <div className="flex items-center gap-2">
                    <span className="text-muted">Mode:</span>
                    <LemonSegmentedButton
                        value={mode}
                        onChange={(newMode) => setMode(newMode)}
                        options={[
                            { value: 'explain', label: 'Explain' },
                            { value: 'fix', label: 'Fix' },
                        ]}
                        size="small"
                    />
                </div>
                <p className="text-muted">
                    {mode === 'explain'
                        ? 'Paste this prompt into your favourite coding assistant to get a detailed explanation of this error:'
                        : 'Paste this prompt into your favourite coding assistant to get help fixing this error:'}
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
