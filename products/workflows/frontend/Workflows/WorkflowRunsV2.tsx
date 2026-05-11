import { HogFunctionRunsV2 } from 'scenes/hog-functions/runs-v2/HogFunctionRunsV2'

/**
 * Workflow-side wrapper around the shared `HogFunctionRunsV2` component,
 * scoped to `function_kind = 'hog_flow'`. The component does all the work —
 * this file exists so the workflow scene can wire its own tab without
 * leaking the cross-product import into every call site.
 */
export function WorkflowRunsV2({ id }: { id: string }): JSX.Element | null {
    return <HogFunctionRunsV2 id={id} functionKind="hog_flow" />
}
