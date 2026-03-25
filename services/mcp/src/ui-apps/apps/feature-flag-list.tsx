import '../styles/tailwind.css'

import type { App } from '@modelcontextprotocol/ext-apps'
import { useCallback } from 'react'
import { createRoot } from 'react-dom/client'

import {
    type FeatureFlagData,
    type FeatureFlagListData,
    FeatureFlagListView,
} from 'products/feature_flags/frontend/mcp-apps'

import { AppWrapper } from '../components/AppWrapper'

function FeatureFlagListApp(): JSX.Element {
    return (
        <AppWrapper<FeatureFlagListData> appName="PostHog Feature Flags">
            {({ data, app }) => <FeatureFlagListContent data={data!} app={app} />}
        </AppWrapper>
    )
}

function FeatureFlagListContent({ data, app }: { data: FeatureFlagListData; app: App | null }): JSX.Element {
    const fallbackToChat = useCallback(
        (flagKey: string) => {
            app?.sendMessage({
                role: 'user',
                content: [{ type: 'text', text: `Show me the details for feature flag "${flagKey}"` }],
            })
        },
        [app]
    )

    const handleFlagClick = useCallback(
        async (flag: FeatureFlagData): Promise<FeatureFlagData | null> => {
            if (!app) {
                fallbackToChat(flag.key)
                return null
            }
            try {
                const result = await app.callServerTool({
                    name: 'feature-flag-get-definition',
                    arguments: { flagId: flag.id },
                })
                if (result.isError || !result.structuredContent) {
                    fallbackToChat(flag.key)
                    return null
                }
                return result.structuredContent as unknown as FeatureFlagData
            } catch {
                fallbackToChat(flag.key)
                return null
            }
        },
        [app, fallbackToChat]
    )

    return <FeatureFlagListView data={data} onFlagClick={handleFlagClick} />
}

const container = document.getElementById('root')
if (container) {
    createRoot(container).render(<FeatureFlagListApp />)
}
