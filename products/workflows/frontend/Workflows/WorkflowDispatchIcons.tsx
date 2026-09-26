import type { DispatchSummaryApi } from 'products/workflows/frontend/generated/api.schemas'

import { getHogFlowDispatchAppearance } from './hogflows/steps/HogFlowSteps'

/** One colored chip per dispatch destination, with how many steps use it. */
export function WorkflowDispatchIcons({ dispatches }: { dispatches: readonly DispatchSummaryApi[] }): JSX.Element {
    return (
        <div className="flex flex-row gap-2 items-center">
            {dispatches.map(({ action_type, template_id, count }) => {
                const appearance = getHogFlowDispatchAppearance(action_type, template_id)
                if (!appearance) {
                    return null
                }
                return (
                    <div
                        key={template_id}
                        className="rounded px-1 flex items-center justify-center gap-1"
                        style={{
                            backgroundColor: `${appearance.color}20`,
                            color: appearance.color,
                        }}
                    >
                        {appearance.icon} {count}
                    </div>
                )
            })}
        </div>
    )
}
