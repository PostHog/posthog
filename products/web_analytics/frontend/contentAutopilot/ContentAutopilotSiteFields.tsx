import { useActions } from 'kea'

import { IconGlobe } from '@posthog/icons'
import { LemonInput } from '@posthog/lemon-ui'

import { LemonField } from 'lib/lemon-ui/LemonField'

import type { ContentAutopilotProfileDraft } from './contentAutopilotLogic'
import { contentAutopilotLogic } from './contentAutopilotLogic'

export const ContentAutopilotSiteFields = ({ draft }: { draft: ContentAutopilotProfileDraft }): JSX.Element => {
    const { setProfileDraft } = useActions(contentAutopilotLogic)

    return (
        <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
            <LemonField.Pure label="Site URL" help="Paste a public page using the site’s final HTTPS address.">
                <LemonInput
                    value={draft.domain}
                    onChange={(domain) => setProfileDraft({ domain })}
                    placeholder="https://example.com"
                    prefix={<IconGlobe />}
                    fullWidth
                />
            </LemonField.Pure>
            <LemonField.Pure label="Site name" help="Leave blank and PostHog will infer it.">
                <LemonInput
                    value={draft.name}
                    onChange={(name) => setProfileDraft({ name })}
                    placeholder="Example docs"
                    fullWidth
                />
            </LemonField.Pure>
        </div>
    )
}
