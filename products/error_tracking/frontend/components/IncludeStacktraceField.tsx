import { LemonCheckbox } from '@posthog/lemon-ui'

import { CodeSnippet } from 'lib/components/CodeSnippet'
import { LemonField } from 'lib/lemon-ui/LemonField'

export function IncludeStacktraceField({ stacktrace }: { stacktrace: string }): JSX.Element | null {
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
