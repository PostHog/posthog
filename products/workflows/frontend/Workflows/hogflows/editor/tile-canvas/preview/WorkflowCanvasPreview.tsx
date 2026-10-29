import { PreviewCanvas } from './PreviewCanvas'
import { PreviewErrorBoundary } from './PreviewErrorBoundary'
import type { WorkflowCanvasPreviewProps } from './workflowCanvasPreviewContract'

export function WorkflowCanvasPreview(props: WorkflowCanvasPreviewProps): JSX.Element {
    return (
        <PreviewErrorBoundary workflow={props}>
            <PreviewCanvas {...props} />
        </PreviewErrorBoundary>
    )
}
