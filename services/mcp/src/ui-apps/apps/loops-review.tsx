import '../styles/tailwind.css'

import type { App } from '@modelcontextprotocol/ext-apps'
import { useCallback, useState } from 'react'
import { createRoot } from 'react-dom/client'

import { LoopReviewView, type LoopReviewData, type LoopReviewState } from 'products/tasks/mcp/apps'

import { AppWrapper } from '../components/AppWrapper'
import { buildReviewedConfig, extractConfirmationHash } from './loops-review-confirm'

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
            const prepared = await app.callServerTool({
                name: 'loops-create-prepare',
                arguments: buildReviewedConfig(data),
            })
            if (prepared.isError) {
                const message =
                    prepared.content?.find((c): c is { type: 'text'; text: string } => c.type === 'text')?.text ??
                    'Failed to create the loop.'
                setState({ loading: false, error: message, createdName: null })
                return
            }
            const confirmationHash = extractConfirmationHash(prepared)
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
