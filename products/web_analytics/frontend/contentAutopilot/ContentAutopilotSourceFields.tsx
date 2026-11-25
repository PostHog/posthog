import { useActions } from 'kea'
import { useId } from 'react'

import { LemonTextArea } from '@posthog/lemon-ui'
import { Field, FieldDescription, FieldLabel, Textarea } from '@posthog/quill'

import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { LemonField } from 'lib/lemon-ui/LemonField'

import type { ContentAutopilotProfileDraft } from './contentAutopilotLogic'
import { contentAutopilotLogic } from './contentAutopilotLogic'

const SOURCES_HELP = 'One same-origin URL per line.'
const BOUNDARIES_HELP = 'PostHog will only research paths with these prefixes.'

export const ContentAutopilotSourceFields = ({ draft }: { draft: ContentAutopilotProfileDraft }): JSX.Element => {
    const { setProfileDraft } = useActions(contentAutopilotLogic)
    const todayRailNav = useFeatureFlag('TODAY_RAIL_NAV')
    const id = useId()

    if (todayRailNav) {
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

    return (
        <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
            <LemonField.Pure label="Sitemaps and factual sources" help={SOURCES_HELP}>
                <LemonTextArea
                    value={draft.sourceUrls}
                    onChange={(sourceUrls) => setProfileDraft({ sourceUrls })}
                    placeholder="https://example.com/sitemap.xml"
                    minRows={4}
                />
            </LemonField.Pure>
            <LemonField.Pure label="Content boundaries" help={BOUNDARIES_HELP}>
                <LemonTextArea
                    value={draft.contentBoundaries}
                    onChange={(contentBoundaries) => setProfileDraft({ contentBoundaries })}
                    placeholder={'/docs\n/blog'}
                    minRows={4}
                />
            </LemonField.Pure>
        </div>
    )
}
