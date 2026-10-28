import { Component, type ReactNode } from 'react'

import { PreviewUnavailable } from './PreviewUnavailable'
import type { WorkflowCanvasPreviewProps } from './workflowCanvasPreviewContract'

type PreviewErrorBoundaryProps = { workflow: WorkflowCanvasPreviewProps; children: ReactNode }

type PreviewErrorBoundaryState = { failed: boolean; workflow: WorkflowCanvasPreviewProps }

function sameWorkflow(a: WorkflowCanvasPreviewProps, b: WorkflowCanvasPreviewProps): boolean {
    return a.actions === b.actions && a.edges === b.edges && a.exitCondition === b.exitCondition
}

/** Agents can save steps the editor cannot read, and one such step must not take the rest of the app down with it. */
export class PreviewErrorBoundary extends Component<PreviewErrorBoundaryProps, PreviewErrorBoundaryState> {
    override state: PreviewErrorBoundaryState = { failed: false, workflow: this.props.workflow }

    static getDerivedStateFromError(): Partial<PreviewErrorBoundaryState> {
        return { failed: true }
    }

    static getDerivedStateFromProps(
        props: PreviewErrorBoundaryProps,
        state: PreviewErrorBoundaryState
    ): PreviewErrorBoundaryState | null {
        return sameWorkflow(props.workflow, state.workflow) ? null : { failed: false, workflow: props.workflow }
    }

    override render(): ReactNode {
        return this.state.failed ? <PreviewUnavailable /> : this.props.children
    }
}
