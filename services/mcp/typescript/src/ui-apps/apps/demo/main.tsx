import '../../styles/base.css'
import './styles.css'

import { createRoot } from 'react-dom/client'

import { useToolResult } from '../../hooks/useToolResult'

function DemoApp(): JSX.Element {
    const { data, isConnected, error, app } = useToolResult<unknown>({
        appName: 'MCP Apps Demo',
    })

    const hostContext = app?.getHostContext()

    if (error) {
        return (
            <div className="demo-container">
                <h1 className="demo-title">MCP Apps Demo</h1>
                <div className="demo-status error">Error: {error.message}</div>
            </div>
        )
    }

    if (!isConnected) {
        return (
            <div className="demo-container">
                <h1 className="demo-title">MCP Apps Demo</h1>
                <div className="demo-status">Connecting to host...</div>
            </div>
        )
    }

    return (
        <div className="demo-container">
            <h1 className="demo-title">MCP Apps Demo</h1>
            <div className="demo-status connected">Connected to host!</div>

            <h2 className="demo-section-title">Connection Info</h2>
            <pre className="demo-data">
                {JSON.stringify(
                    {
                        isConnected,
                        hasHostStyles: !!hostContext?.styles,
                        hasHostFonts: !!hostContext?.fonts,
                    },
                    null,
                    2
                )}
            </pre>

            {data ? (
                <>
                    <h2 className="demo-section-title">Tool Result Data</h2>
                    <pre className="demo-data">{JSON.stringify(data, null, 2)}</pre>
                </>
            ) : (
                <>
                    <h2 className="demo-section-title">Waiting for Tool Result</h2>
                    <p style={{ color: 'var(--color-text-secondary)', fontSize: '0.875rem' }}>
                        Call the <code>demo-mcp-ui-apps</code> tool to see data here!
                    </p>
                </>
            )}
        </div>
    )
}

const container = document.getElementById('root')
if (container) {
    createRoot(container).render(<DemoApp />)
}
