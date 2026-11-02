import { useState } from 'react'

import { PreviewCanvas } from './PreviewCanvas'
import { PreviewErrorBoundary } from './PreviewErrorBoundary'
import type { WorkflowCanvasPreviewProps } from './workflowCanvasPreviewContract'

export function WorkflowCanvasPreview(props: WorkflowCanvasPreviewProps): JSX.Element {
    const canvas = useCanvasKey(props)
    return (
        <PreviewErrorBoundary workflow={props}>
            <PreviewCanvas key={canvas} {...props} />
        </PreviewErrorBoundary>
    )
}

function useCanvasKey({ actions, edges }: WorkflowCanvasPreviewProps): number {
    const [shown, setShown] = useState({ actions, edges, key: 0 })
    if (shown.actions !== actions || shown.edges !== edges) {
        const next = { actions, edges, key: shown.key + 1 }
        setShown(next)
        return next.key
    }
    return shown.key
}
