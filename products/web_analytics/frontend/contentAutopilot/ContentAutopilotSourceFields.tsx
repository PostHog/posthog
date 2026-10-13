import { useActions } from 'kea'

import { LemonCheckbox, LemonTextArea } from '@posthog/lemon-ui'

import { LemonField } from 'lib/lemon-ui/LemonField'

import type { ContentAutopilotProfileDraft } from './contentAutopilotLogic'
import { contentAutopilotLogic } from './contentAutopilotLogic'

export const ContentAutopilotSourceFields = ({ draft }: { draft: ContentAutopilotProfileDraft }): JSX.Element => {
    const { setProfileDraft } = useActions(contentAutopilotLogic)

    return (
        <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
            <LemonField.Pure label="Sitemaps and factual sources" help="One same-origin URL per line.">
                <LemonTextArea
                    value={draft.sourceUrls}
                    onChange={(sourceUrls) => setProfileDraft({ sourceUrls })}
                    placeholder="https://example.com/sitemap.xml"
                    minRows={4}
                />
            </LemonField.Pure>
            <LemonField.Pure label="Content boundaries" help="PostHog will only research paths with these prefixes.">
                <LemonTextArea
                    value={draft.contentBoundaries}
                    onChange={(contentBoundaries) => setProfileDraft({ contentBoundaries })}
                    placeholder={'/docs\n/blog'}
                    minRows={4}
                />
            </LemonField.Pure>
            <LemonCheckbox
                checked={draft.searchConsoleEnabled}
                onChange={(searchConsoleEnabled) => setProfileDraft({ searchConsoleEnabled })}
                label="Use connected Google Search Console data"
            />
        </div>
    )
}
