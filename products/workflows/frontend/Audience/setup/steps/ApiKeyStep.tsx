import { combineUrl } from 'kea-router'

import { LemonButton } from '@posthog/lemon-ui'

import { urls } from 'scenes/urls'

import { SetupStepCard } from '../SetupStepCard'

// pinned: `preset` is an API_KEY_SCOPE_PRESETS value that the personal API keys settings read from the URL
const EMAIL_PREFERENCE_KEY_URL = combineUrl(urls.settings('user-api-keys'), { preset: 'messaging_preferences' }).url

export function ApiKeyStep(): JSX.Element {
    return (
        <SetupStepCard
            title="Create a personal API key"
            description={
                <>
                    Your backend uses it to send preferences. It needs the <code>hog_flow:write</code> scope, and its
                    owner needs edit access to workflows in this project. Store it as{' '}
                    <code>POSTHOG_PERSONAL_API_KEY</code>.
                </>
            }
            dataAttr="audience-setup-api-key"
        >
            <div className="flex">
                <LemonButton
                    type="secondary"
                    to={EMAIL_PREFERENCE_KEY_URL}
                    targetBlank
                    data-attr="audience-setup-create-api-key"
                >
                    Create personal API key
                </LemonButton>
            </div>
        </SetupStepCard>
    )
}
