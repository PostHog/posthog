import { useValues } from 'kea'

import { LemonCheckbox } from '@posthog/lemon-ui'

import { CodeSnippet } from 'lib/components/CodeSnippet'
import { stackFrameLogic } from 'lib/components/Errors/Frame/stackFrameLogic'
import { ErrorEventType } from 'lib/components/Errors/types'
import { LemonField } from 'lib/lemon-ui/LemonField'

import { getStacktrace } from './externalIssueBody'

export function IncludeStacktraceField({ event }: { event: ErrorEventType | null }): JSX.Element | null {
    const { stackFrameRecords } = useValues(stackFrameLogic)
    const stacktrace = getStacktrace(event, stackFrameRecords)

    if (!stacktrace) {
        return null
    }

    return (
        <LemonField name="includeStacktrace">
            {({ value, onChange }) => (
                <div className="flex flex-col gap-y-2">
                    <LemonCheckbox
                        data-attr="external-issue-include-stacktrace"
                        checked={!!value}
                        onChange={onChange}
                        label="Include stack trace"
                    />
                    {value && (
                        <CodeSnippet compact wrap thing="stack trace" maxLinesWithoutExpansion={3}>
                            {stacktrace}
                        </CodeSnippet>
                    )}
                </div>
            )}
        </LemonField>
    )
}
