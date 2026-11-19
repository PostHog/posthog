import type { ReactElement } from 'react'
import { ChatVisualization } from './ChatVisualization'

export function InsightCard({ shortId, title }: { shortId: string; title?: string }): ReactElement {
    return <ChatVisualization shortId={shortId} title={title} />
}
