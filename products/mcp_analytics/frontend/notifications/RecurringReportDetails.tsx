import { useState } from 'react'

import { Link } from '@posthog/lemon-ui'

/**
 * The report itself is written by an LLM each run, so there is nothing faithful to preview. The
 * coverage list says what a delivery answers; the question handed to the model stays behind a
 * disclosure because it is written for the model, not the reader, and is editable before saving.
 */
export function RecurringReportDetails({ covers, prompt }: { covers: string[]; prompt: string }): JSX.Element {
    const [promptShown, setPromptShown] = useState(false)

    return (
        <div className="flex flex-col gap-1">
            <div className="text-xs font-medium text-muted">What it covers</div>
            <ul className="m-0 list-disc pl-4 text-sm">
                {covers.map((line) => (
                    <li key={line}>{line}</li>
                ))}
            </ul>
            <Link
                className="text-xs"
                onClick={() => setPromptShown(!promptShown)}
                data-attr="mcp-analytics-recurring-report-toggle-prompt"
            >
                {promptShown ? 'Hide the question it asks' : 'Show the question it asks'}
            </Link>
            {promptShown && <p className="m-0 text-sm text-muted">{prompt}</p>}
        </div>
    )
}
