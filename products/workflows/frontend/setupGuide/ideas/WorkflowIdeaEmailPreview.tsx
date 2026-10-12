import { useState } from 'react'

import { LemonSegmentedButton } from '@posthog/lemon-ui'

import type { IdeaEmailPreview } from './ideaCopy'
import { waitLabel } from './ideaCopy'

/** The emails of an idea as recipients would get them, one at a time. */
export function WorkflowIdeaEmailPreview({
    emails,
    waits,
}: {
    emails: IdeaEmailPreview[]
    waits: string[]
}): JSX.Element {
    const [index, setIndex] = useState(0)
    const email = emails[index]

    return (
        <div className="flex flex-col gap-3" data-attr="workflow-idea-preview">
            {emails.length > 1 && (
                <LemonSegmentedButton
                    size="small"
                    value={index}
                    onChange={setIndex}
                    options={emails.map((_, position) => ({
                        value: position,
                        label: `Email ${position + 1}${waits[position] ? ` · after ${waitLabel(waits[position])}` : ''}`,
                    }))}
                />
            )}
            <div className="flex flex-col gap-0.5 rounded border bg-surface-secondary p-2 text-sm">
                <div>
                    <span className="text-secondary">Subject:</span> <strong>{email.subject}</strong>
                </div>
                {email.preheader && (
                    <div className="text-xs text-secondary">
                        <span>Preview text:</span> {email.preheader}
                    </div>
                )}
            </div>
            <iframe
                title={`Email ${index + 1}`}
                className="h-[26rem] w-full rounded border bg-white"
                // Scripts stay off: the HTML only has to render.
                sandbox=""
                srcDoc={email.html}
            />
            <p className="mb-0 text-xs text-secondary">
                You can change the wording, design and links in the email editor after you use this workflow.
            </p>
        </div>
    )
}
