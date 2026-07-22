import '../styles/tailwind.css'

import type { App } from '@modelcontextprotocol/ext-apps'
import { useCallback, useState } from 'react'
import { createRoot } from 'react-dom/client'

import { LoopReviewView, type LoopReviewData, type LoopReviewState } from 'products/tasks/mcp/apps'

import { AppWrapper } from '../components/AppWrapper'
import { APP_DATA_META_KEY } from '../types'

function LoopReviewApp(): JSX.Element {
    return (
        <AppWrapper<LoopReviewData> appName="PostHog Loop Review">
            {({ data, app }) => <LoopReviewContent data={data!} app={app} />}
        </AppWrapper>
    )
}

function LoopReviewContent({ data, app }: { data: LoopReviewData; app: App | null }): JSX.Element {
    const [state, setState] = useState<LoopReviewState>({ loading: false, error: null, createdName: null })

    const handleCreate = useCallback(async (): Promise<void> => {
        if (!app) {
            setState({
                loading: false,
                error: 'Creating loops is not available in this host. Ask the agent to create it in chat.',
                createdName: null,
            })
            return
        }
        setState({ loading: true, error: null, createdName: null })
        try {
            // `loops-create` is a confirmed action (prepare/execute) and this click is the human
            // confirmation step, so only fields the card renders may travel: anything else in
            // `data` would be created without ever being reviewed.
            const reviewedConfig: Record<string, unknown> = {
                name: data.name,
                description: data.description,
                visibility: data.visibility,
                instructions: data.instructions,
                runtime_adapter: data.runtime_adapter,
                model: data.model,
                reasoning_effort: data.reasoning_effort,
                repositories: data.repositories,
                triggers: data.triggers,
                enabled: data.enabled,
                overlap_policy: data.overlap_policy,
                behaviors: data.behaviors,
                connectors: data.connectors,
                sandbox_environment: data.sandbox_environment,
                notifications: data.notifications,
                context_target: data.context_target,
            }
            const prepared = await app.callServerTool({
                name: 'loops-create-prepare',
                arguments: reviewedConfig,
            })
            if (prepared.isError) {
                const message =
                    prepared.content?.find((c): c is { type: 'text'; text: string } => c.type === 'text')?.text ??
                    'Failed to create the loop.'
                setState({ loading: false, error: message, createdName: null })
                return
            }
            const preparedData = ((prepared._meta as Record<string, unknown> | undefined)?.[APP_DATA_META_KEY] ??
                prepared.structuredContent) as { confirmation_hash?: string } | undefined
            const confirmationHash = preparedData?.confirmation_hash
            if (!confirmationHash) {
                setState({
                    loading: false,
                    error: 'Failed to create the loop: the server did not return a confirmation hash.',
                    createdName: null,
                })
                return
            }
            const result = await app.callServerTool({
                name: 'loops-create-execute',
                arguments: { confirmation_hash: confirmationHash, confirmation: 'confirm' },
            })
            if (result.isError) {
                const message =
                    result.content?.find((c): c is { type: 'text'; text: string } => c.type === 'text')?.text ??
                    'Failed to create the loop.'
                setState({ loading: false, error: message, createdName: null })
                return
            }
            setState({ loading: false, error: null, createdName: data.name?.trim() || 'Your loop' })
        } catch (err) {
            const message = err instanceof Error ? err.message : String(err)
            setState({ loading: false, error: message, createdName: null })
        }
    }, [app, data])

    return <LoopReviewView data={data} onCreate={handleCreate} state={state} />
}

const container = document.getElementById('root')
if (container) {
    createRoot(container).render(<LoopReviewApp />)
}
