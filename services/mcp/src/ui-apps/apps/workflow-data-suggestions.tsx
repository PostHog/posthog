import '../styles/tailwind.css'

import type { App } from '@modelcontextprotocol/ext-apps'
import { useCallback, useState } from 'react'
import { createRoot } from 'react-dom/client'

import {
    type WorkflowDataSuggestion,
    type WorkflowDataSuggestionBuild,
    type WorkflowDataSuggestionMissingInput,
    type WorkflowDataSuggestionsData,
    WorkflowDataSuggestionsView,
} from 'products/workflows/mcp/apps'

import { AppWrapper } from '../components/AppWrapper'

const CHECK_INTERVAL_MS = 3000
// A build runs in the background, usually for 10 to 60 seconds. Past this the card stops checking and says so.
const CHECK_DEADLINE_MS = 3 * 60 * 1000
const BUILD_FAILED = "We couldn't build this workflow. Try again, or pick another suggestion."

interface BuildResult {
    status: 'ready' | 'building' | 'failed'
    workflow_id?: string | null
    missing_inputs?: WorkflowDataSuggestionMissingInput[]
    _posthogUrl?: string
}

function WorkflowDataSuggestionsApp(): JSX.Element {
    return (
        <AppWrapper<WorkflowDataSuggestionsData> appName="PostHog Workflow Suggestions">
            {({ data, app }) => <WorkflowDataSuggestionsContent data={data!} app={app} />}
        </AppWrapper>
    )
}

function WorkflowDataSuggestionsContent({
    data,
    app,
}: {
    data: WorkflowDataSuggestionsData
    app: App | null
}): JSX.Element {
    const [builds, setBuilds] = useState<Record<string, WorkflowDataSuggestionBuild>>({})
    const setBuild = useCallback(
        (id: string, build: WorkflowDataSuggestionBuild) => setBuilds((current) => ({ ...current, [id]: build })),
        []
    )

    const askInChat = useCallback(
        (suggestion: WorkflowDataSuggestion): void => {
            app?.sendMessage({
                role: 'user',
                content: [{ type: 'text', text: `Create a workflow from the suggestion "${suggestion.name}"` }],
            })
        },
        [app]
    )

    const handleCreate = useCallback(
        async (suggestion: WorkflowDataSuggestion, retry: boolean): Promise<void> => {
            if (!app) {
                return
            }
            setBuild(suggestion.id, { status: 'building' })
            const deadline = Date.now() + CHECK_DEADLINE_MS
            let firstCall = true
            while (Date.now() < deadline) {
                let result: Awaited<ReturnType<App['callServerTool']>>
                try {
                    result = await app.callServerTool({
                        name: 'workflows-data-suggestions-create',
                        arguments: { suggestion_id: suggestion.id, retry: firstCall && retry },
                    })
                } catch {
                    if (firstCall) {
                        // The host cannot call tools from an app, so the agent creates it from the chat instead.
                        setBuilds(({ [suggestion.id]: _dropped, ...rest }) => rest)
                        askInChat(suggestion)
                    } else {
                        setBuild(suggestion.id, { status: 'failed', error: BUILD_FAILED })
                    }
                    return
                }
                firstCall = false
                const built = result.structuredContent as unknown as BuildResult | undefined
                if (result.isError || !built || built.status === 'failed') {
                    setBuild(suggestion.id, { status: 'failed', error: BUILD_FAILED })
                    return
                }
                if (built.status === 'ready' && built.workflow_id) {
                    setBuild(suggestion.id, {
                        status: 'ready',
                        editorUrl: built._posthogUrl ?? null,
                        missingInputs: built.missing_inputs ?? [],
                    })
                    return
                }
                await new Promise((resolve) => setTimeout(resolve, CHECK_INTERVAL_MS))
            }
            setBuild(suggestion.id, { status: 'failed', error: BUILD_FAILED })
        },
        [app, askInChat, setBuild]
    )

    return (
        <WorkflowDataSuggestionsView
            data={data}
            builds={builds}
            onCreate={(suggestion, retry) => void handleCreate(suggestion, retry)}
        />
    )
}

const container = document.getElementById('root')
if (container) {
    createRoot(container).render(<WorkflowDataSuggestionsApp />)
}
