import { useActions, useValues } from 'kea'

import { mcpAnalyticsToolDetailLogic } from '../mcpAnalyticsToolDetailLogic'
import { SessionDrawer } from '../sessions/SessionDrawer'

export function ExampleSessionDrawer(): JSX.Element | null {
    const { selectedExample } = useValues(mcpAnalyticsToolDetailLogic)
    const { openExample } = useActions(mcpAnalyticsToolDetailLogic)

    if (!selectedExample?.sessionId) {
        return null
    }
    return (
        <SessionDrawer
            sessionId={selectedExample.sessionId}
            timestamp={selectedExample.timestamp}
            focusedEventId={selectedExample.uuid}
            stacked
            onClose={() => openExample(null)}
            dataAttr="mcp-tool-example-session-drawer"
        />
    )
}
