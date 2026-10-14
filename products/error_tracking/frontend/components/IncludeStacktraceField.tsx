import { BuiltLogic, useValues } from 'kea'
import { FormContext } from 'kea-forms'
import { useContext } from 'react'

import { LemonCheckbox } from '@posthog/lemon-ui'

import { CodeSnippet } from 'lib/components/CodeSnippet'
import { stackFrameLogic } from 'lib/components/Errors/Frame/stackFrameLogic'
import { LemonField } from 'lib/lemon-ui/LemonField'

import type { errorTrackingIssueSceneLogicType } from '../scenes/ErrorTrackingIssueScene/errorTrackingIssueSceneLogic'
import { MAX_ISSUE_BODY_LENGTH, fitStacktrace, getStacktrace } from './externalIssueBody'

export function IncludeStacktraceField({
    sceneLogic,
    bodyField,
}: {
    sceneLogic: BuiltLogic<errorTrackingIssueSceneLogicType>
    bodyField: string
}): JSX.Element | null {
    // The event can finish loading after the dialog opens, so it is read from the scene rather than passed in.
    const { selectedEvent, initialEvent } = useValues(sceneLogic)
    const { stackFrameRecords } = useValues(stackFrameLogic)
    // How much of the trace fits depends on the body, which lives in the dialog's form.
    const { logic: formLogic, formKey } = useContext(FormContext)
    const body: string = useValues(formLogic as BuiltLogic)[formKey]?.[bodyField] ?? ''

    const stacktrace = getStacktrace(selectedEvent ?? initialEvent, stackFrameRecords)
    const trace = fitStacktrace(body, stacktrace)

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
                    {value && trace && (
                        <CodeSnippet compact wrap thing="stack trace" maxLinesWithoutExpansion={3}>
                            {trace}
                        </CodeSnippet>
                    )}
                    {value && trace !== stacktrace && (
                        <span className="text-xs text-secondary">
                            {trace
                                ? `The end is cut to keep the issue under ${MAX_ISSUE_BODY_LENGTH.toLocaleString()} characters.`
                                : 'The body is too long to add the stack trace.'}
                        </span>
                    )}
                </div>
            )}
        </LemonField>
    )
}
