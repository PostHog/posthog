import '../styles/tailwind.css'

import type { App } from '@modelcontextprotocol/ext-apps'
import { useCallback, useState } from 'react'
import { createRoot } from 'react-dom/client'

import { LoopReviewView, type LoopReviewData, type LoopReviewState } from 'products/tasks/mcp/apps'

import { AppWrapper } from '../components/AppWrapper'

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
            // Forward the reviewed config unchanged — `loops-review`'s schema is the
            // `loops-create` body, so `data` is already a valid create payload.
            const result = await app.callServerTool({
                name: 'loops-create',
                arguments: data as Record<string, unknown>,
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
