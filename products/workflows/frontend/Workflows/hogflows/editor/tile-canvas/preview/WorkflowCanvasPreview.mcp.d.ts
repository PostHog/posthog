import type { ReactElement } from 'react'

import type { WorkflowCanvasPreviewProps } from './workflowCanvasPreviewContract'

// The MCP apps typecheck against this declaration, so their stricter compiler never walks the editor's imports.
export declare function WorkflowCanvasPreview(props: WorkflowCanvasPreviewProps): ReactElement
