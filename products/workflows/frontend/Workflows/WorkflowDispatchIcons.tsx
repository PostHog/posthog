import { getHogFlowDispatchAppearance } from './hogflows/steps/HogFlowSteps'

export interface WorkflowDispatch {
    actionType: string
    /** The function template id, or the action type for steps without one. */
    templateId: string
    count: number
}

/** One colored chip per dispatch destination, with how many steps use it. */
export function WorkflowDispatchIcons({ dispatches }: { dispatches: WorkflowDispatch[] }): JSX.Element {
    return (
        <div className="flex flex-row gap-2 items-center">
            {dispatches.map(({ actionType, templateId, count }) => {
                const appearance = getHogFlowDispatchAppearance(actionType, templateId, {})
                if (!appearance) {
                    return null
                }
                return (
                    <div
                        key={templateId}
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
