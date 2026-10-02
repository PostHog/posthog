import { useActions, useValues } from 'kea'

import { LemonBanner, LemonSkeleton, Link } from '@posthog/lemon-ui'

import { urls } from 'scenes/urls'

import { audienceSetupLogic } from '../audienceSetupLogic'
import { PreferenceSnippetTabs } from '../PreferenceSnippetTabs'
import { SetupStepCard } from '../SetupStepCard'

function TopicsLoadFailedBanner(): JSX.Element {
    const { loadCategories } = useActions(audienceSetupLogic)
    return (
        <LemonBanner
            type="error"
            action={{ children: 'Try again', onClick: loadCategories, 'data-attr': 'audience-setup-retry-topics' }}
        >
            Couldn't load your topics, so the snippet can't list their keys. Try again in a moment.
        </LemonBanner>
    )
}

function SnippetBody(): JSX.Element {
    const { categoriesLoading, categoriesLoadFailed } = useValues(audienceSetupLogic)

    if (categoriesLoading) {
        return <LemonSkeleton className="h-60" />
    }
    return categoriesLoadFailed ? <TopicsLoadFailedBanner /> : <PreferenceSnippetTabs />
}

export function SendPreferencesStep(): JSX.Element {
    return (
        <SetupStepCard
            title="Send preferences from your app"
            description={
                <>
                    Call <code>setPreferences</code> wherever users save their email preferences. Copy the snippet, or
                    give the prompt to your coding agent.
                </>
            }
            dataAttr="audience-setup-send-preferences"
        >
            <SnippetBody />
            <p className="text-secondary text-xs m-0">
                Topic keys come from the <Link to={urls.audience('topics')}>Topics</Link> tab.
            </p>
        </SetupStepCard>
    )
}
