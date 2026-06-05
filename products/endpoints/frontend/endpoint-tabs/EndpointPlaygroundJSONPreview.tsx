import { useValues } from 'kea'

import { LemonCollapse } from '@posthog/lemon-ui'

import { CodeSnippet, Language } from 'lib/components/CodeSnippet'

import { endpointSceneLogic } from '../endpointSceneLogic'

export function EndpointPlaygroundJSONPreview(): JSX.Element {
    const { playgroundPayloadJsonPreview } = useValues(endpointSceneLogic)

    return (
        <LemonCollapse
            multiple
            defaultActiveKeys={['preview']}
            panels={[
                {
                    key: 'preview',
                    header: <span className="text-sm">Request payload (preview)</span>,
                    content: (
                        <div className="p-1">
                            <p className="text-xs text-secondary mb-2">
                                Read-only. This is the exact JSON body the playground will POST to /run.
                            </p>
                            <CodeSnippet language={Language.JSON} wrap>
                                {playgroundPayloadJsonPreview}
                            </CodeSnippet>
                        </div>
                    ),
                },
            ]}
        />
    )
}
