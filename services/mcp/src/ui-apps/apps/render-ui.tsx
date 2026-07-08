import '../styles/tailwind.css'

import type { App } from '@modelcontextprotocol/ext-apps'
import { useEffect, useState } from 'react'
import { createRoot } from 'react-dom/client'

import type { UiAppKey } from '../../resources/ui-apps.generated'
import { AppErrorState, AppLoadingState, AppWrapper } from '../components/AppWrapper'
import { RENDER_DISPATCH } from '../generated/render-dispatch.generated'

/**
 * Envelope emitted by the `render-ui` server tool. It carries the tool to render
 * and its input — never the data itself. This app fetches the data via
 * `callServerTool` (the same path the list apps use for drill-down) and mounts
 * the matching view from the generated dispatch registry.
 */
interface RenderUiEnvelope {
    tool_name: string
    tool_input?: Record<string, unknown>
    app_key: UiAppKey
}

function RenderUiApp(): JSX.Element {
    return (
        <AppWrapper<RenderUiEnvelope> appName="PostHog Render UI">
            {({ data, app, openLink }) => <RenderUiContent envelope={data!} app={app} openLink={openLink} />}
        </AppWrapper>
    )
}

function RenderUiContent({
    envelope,
    app,
    openLink,
}: {
    envelope: RenderUiEnvelope
    app: App | null
    openLink: (url: string) => void
}): JSX.Element {
    const [data, setData] = useState<unknown>(null)
    const [error, setError] = useState<string | null>(null)

    // Key the fetch on serialized values, not `envelope` identity — a parent
    // re-render with a fresh-but-equal envelope object must not refetch.
    const toolName = envelope.tool_name
    const toolInputJson = JSON.stringify(envelope.tool_input ?? {})
    useEffect(() => {
        if (!app) {
            setError('Visualization unavailable: app context not provided.')
            return
        }
        let cancelled = false
        setData(null)
        setError(null)
        app.callServerTool({ name: toolName, arguments: JSON.parse(toolInputJson) as Record<string, unknown> })
            .then((result) => {
                if (cancelled) {
                    return
                }
                if (result.isError || !result.structuredContent) {
                    setError(`Could not load data for ${toolName}.`)
                    return
                }
                setData(result.structuredContent)
            })
            .catch((e: unknown) => {
                if (!cancelled) {
                    setError(e instanceof Error ? e.message : String(e))
                }
            })
        return () => {
            cancelled = true
        }
    }, [app, toolName, toolInputJson])

    const render = RENDER_DISPATCH[envelope.app_key]
    if (!render) {
        return <AppErrorState message={`No visualization is available for ${envelope.tool_name}.`} />
    }
    if (error) {
        return <AppErrorState message={error} />
    }
    if (data === null) {
        return <AppLoadingState />
    }
    return render({ data, app, openLink })
}

const container = document.getElementById('root')
if (container) {
    createRoot(container).render(<RenderUiApp />)
}
