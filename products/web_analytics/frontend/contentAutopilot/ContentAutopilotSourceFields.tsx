import { useActions } from 'kea'
import { useId } from 'react'

import { Field, FieldDescription, FieldLabel, Textarea } from '@posthog/quill'

import type { ContentAutopilotProfileDraft } from './contentAutopilotLogic'
import { contentAutopilotLogic } from './contentAutopilotLogic'

const SOURCES_HELP = 'One same-origin URL per line.'
const BOUNDARIES_HELP = 'PostHog will only research paths with these prefixes.'

export const ContentAutopilotSourceFields = ({ draft }: { draft: ContentAutopilotProfileDraft }): JSX.Element => {
    const { setProfileDraft } = useActions(contentAutopilotLogic)
    const id = useId()

    return (
        <div className="grid grid-cols-1 gap-4 @min-[48rem]/main-content:grid-cols-2">
            <Field>
                <FieldLabel htmlFor={`${id}-sources`}>Sitemaps and factual sources</FieldLabel>
                <Textarea
                    id={`${id}-sources`}
                    value={draft.sourceUrls}
                    onChange={(event) => setProfileDraft({ sourceUrls: event.target.value })}
                    placeholder="https://example.com/sitemap.xml"
                    rows={4}
                />
                <FieldDescription>{SOURCES_HELP}</FieldDescription>
            </Field>
            <Field>
                <FieldLabel htmlFor={`${id}-boundaries`}>Content boundaries</FieldLabel>
                <Textarea
                    id={`${id}-boundaries`}
                    value={draft.contentBoundaries}
                    onChange={(event) => setProfileDraft({ contentBoundaries: event.target.value })}
                    placeholder={'/docs\n/blog'}
                    rows={4}
                />
                <FieldDescription>{BOUNDARIES_HELP}</FieldDescription>
            </Field>
        </div>
    )
}
