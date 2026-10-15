import { type ReactElement } from 'react'

import type { WorkflowDataSuggestionBuild } from './WorkflowDataSuggestionsView'

export function WorkflowDataSuggestionBuildView({ build }: { build: WorkflowDataSuggestionBuild }): ReactElement {
    if (build.status === 'building') {
        return <p className="m-0 text-sm text-muted-foreground">Building your workflow. This takes up to a minute.</p>
    }
    if (build.status === 'failed') {
        return <p className="m-0 text-sm text-destructive">{build.error}</p>
    }
    return (
        <div className="flex flex-col gap-1 text-sm">
            <div className="flex flex-wrap items-center gap-3">
                <span className="font-medium">Draft saved. It doesn't run until you enable it.</span>
                {build.editorUrl ? (
                    <a className="text-link underline" href={build.editorUrl} target="_blank" rel="noopener noreferrer">
                        Open in PostHog
                    </a>
                ) : null}
            </div>
            {build.missingInputs.length > 0 ? (
                <div className="text-muted-foreground">
                    Still to set before you enable it:
                    <ul className="m-0 pl-5">
                        {build.missingInputs.map((input, index) => (
                            <li key={index}>
                                {input.field} in "{input.step_name}"
                            </li>
                        ))}
                    </ul>
                </div>
            ) : null}
        </div>
    )
}
