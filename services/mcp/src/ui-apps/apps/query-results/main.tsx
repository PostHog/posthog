import '../../styles/base.css'

import { createRoot } from 'react-dom/client'

import { Component } from '../../components/Component'
import { useToolResult } from '../../hooks/useToolResult'

function QueryResultsApp(): JSX.Element {
    const { data, isConnected, error, openLink } = useToolResult({
        appName: 'PostHog Query Results',
    })

    if (error) {
        return <div className="error">{error.message}</div>
    }

    if (!isConnected) {
        return <div className="loading">Connecting to host...</div>
    }

    if (!data) {
        return <div className="loading">Waiting for data</div>
    }

    return <Component data={data} onOpenLink={openLink} />
}

const container = document.getElementById('root')
if (container) {
    createRoot(container).render(<QueryResultsApp />)
}
