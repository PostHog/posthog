import { useActions, useValues } from 'kea'

import { LemonTabs } from '@posthog/lemon-ui'

import { CodeSnippet, Language } from 'lib/components/CodeSnippet'

import { AudienceSnippetVariant, audienceSetupLogic } from './audienceSetupLogic'

export function PreferenceSnippetTabs(): JSX.Element {
    const { snippetVariant, nodeSnippet, agentPrompt } = useValues(audienceSetupLogic)
    const { setSnippetVariant, trackSnippetCopied } = useActions(audienceSetupLogic)

    return (
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
    )
}
