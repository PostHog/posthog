import { useActions, useValues } from 'kea'

import { LemonTabs, Link } from '@posthog/lemon-ui'

import { CodeSnippet, Language } from 'lib/components/CodeSnippet'
import { urls } from 'scenes/urls'

import { AudienceSnippetVariant, audienceSetupLogic } from '../audienceSetupLogic'
import { SetupStepCard } from '../SetupStepCard'

export function SendPreferencesStep(): JSX.Element {
    const { snippetVariant, nodeSnippet, agentPrompt } = useValues(audienceSetupLogic)
    const { setSnippetVariant, trackSnippetCopied } = useActions(audienceSetupLogic)

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
            <LemonTabs<AudienceSnippetVariant>
                size="small"
                activeKey={snippetVariant}
                onChange={setSnippetVariant}
                tabs={[
                    {
                        key: 'snippet',
                        label: 'posthog-node',
                        content: (
                            <CodeSnippet
                                language={Language.JavaScript}
                                thing="snippet"
                                onCopy={() => trackSnippetCopied('snippet')}
                            >
                                {nodeSnippet}
                            </CodeSnippet>
                        ),
                    },
                    {
                        key: 'agent_prompt',
                        label: 'Prompt for your coding agent',
                        content: (
                            <CodeSnippet
                                language={Language.Text}
                                thing="prompt"
                                wrap
                                onCopy={() => trackSnippetCopied('agent_prompt')}
                            >
                                {agentPrompt}
                            </CodeSnippet>
                        ),
                    },
                ]}
            />
            <p className="text-secondary text-xs m-0">
                Topic keys come from the <Link to={urls.audience('topics')}>Topics</Link> tab.
            </p>
        </SetupStepCard>
    )
}
