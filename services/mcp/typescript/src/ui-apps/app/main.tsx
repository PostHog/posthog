import { createRoot } from 'react-dom/client'
import { useState, useEffect, useCallback } from 'react'
import { App, PostMessageTransport, applyHostStyleVariables, type McpUiToolResultNotification } from '@modelcontextprotocol/ext-apps'
import { Component } from '../components/Component'
import '../styles/base.css'

type ToolResultParams = McpUiToolResultNotification['params']

function parseToolResult(params: ToolResultParams): unknown {
    // Prefer structuredContent if available
    if (params.structuredContent) {
        return params.structuredContent
    }

    // Fall back to parsing text content
    if (params.content && Array.isArray(params.content)) {
        for (const item of params.content) {
            if (item.type === 'text' && 'text' in item && typeof item.text === 'string') {
                try {
                    return JSON.parse(item.text)
                } catch {
                    continue
                }
            }
        }
    }

    return null
}

function AppRoot(): JSX.Element {
    const [app, setApp] = useState<App | null>(null)
    const [data, setData] = useState<unknown>(null)
    const [error, setError] = useState<string | null>(null)

    useEffect(() => {
        const appInstance = new App(
            { name: 'PostHog Visualizer', version: '1.0.0' },
            {}
        )

        appInstance.ontoolresult = (params: ToolResultParams) => {
            try {
                const parsed = parseToolResult(params)
                if (parsed) {
                    setData(parsed)
                    setError(null)
                } else {
                    setError('Unable to parse tool result')
                }
            } catch (e) {
                setError(`Error parsing result: ${e instanceof Error ? e.message : String(e)}`)
            }
        }

        appInstance.onhostcontextchanged = (context) => {
            if (context.styles) {
                applyHostStyleVariables(context.styles)
            }
        }

        const transport = new PostMessageTransport(window.parent, window)
        appInstance.connect(transport).then(() => {
            const hostContext = appInstance.getHostContext()
            if (hostContext?.styles) {
                applyHostStyleVariables(hostContext.styles)
            }
        }).catch((e) => {
            setError(`Connection error: ${e instanceof Error ? e.message : String(e)}`)
        })

        setApp(appInstance)
    }, [])

    const handleOpenLink = useCallback(
        (url: string) => {
            if (app) {
                app.openLink({ url })
            } else {
                window.open(url, '_blank', 'noopener,noreferrer')
            }
        },
        [app]
    )

    if (error) {
        return <div className="error">{error}</div>
    }

    if (!data) {
        return <div className="loading">Waiting for data</div>
    }

    return <Component data={data} onOpenLink={handleOpenLink} />
}

const container = document.getElementById('root')
if (container) {
    const root = createRoot(container)
    root.render(<AppRoot />)
}
