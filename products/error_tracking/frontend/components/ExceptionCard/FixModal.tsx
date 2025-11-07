import posthog from 'posthog-js'

import { LemonButton, LemonModal } from '@posthog/lemon-ui'

import { copyToClipboard } from 'lib/utils/copyToClipboard'

import { useStacktraceDisplay } from '../../hooks/use-stacktrace-display'

interface FixModalProps {
    isOpen: boolean
    onClose: () => void
}

export function FixModal({ isOpen, onClose }: FixModalProps): JSX.Element {
    const { stacktraceText } = useStacktraceDisplay()

    const generatePrompt = (): string => {
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
