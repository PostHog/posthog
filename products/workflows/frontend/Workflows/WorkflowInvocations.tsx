import { HogInvocations } from 'scenes/hog-functions/invocations/HogInvocations'

/**
 * Workflow-side wrapper around the shared `HogInvocations` component,
 * scoped to `function_kind = 'hog_flow'`. The component does all the work —
 * this file exists so the workflow scene can wire its own tab without
 * leaking the cross-product import into every call site.
 */
export function WorkflowInvocations({ id }: { id: string }): JSX.Element | null {
    return <HogInvocations id={id} functionKind="hog_flow" />
}
