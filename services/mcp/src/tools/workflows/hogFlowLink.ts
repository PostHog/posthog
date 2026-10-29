type FlowStep = {
    id?: string
    type?: string
    config?: { type?: string; filters?: { audience_type?: string } | null } | null
}
type FlowEdge = { from?: string; to?: string }

export type HogFlowLike = {
    id?: string
    status?: string | null
    origin_product?: string | null
    exit_condition?: string | null
    draft?: unknown
    actions?: FlowStep[] | null
    edges?: FlowEdge[] | null
}

/** The app path a hog flow opens at: broadcasts have their own scene, everything else is the workflow editor. */
export function hogFlowPath(flow: { id: string; origin_product?: string | null }): string {
    return flow.origin_product === 'broadcasts' ? `/broadcasts/${flow.id}` : `/workflows/${flow.id}/workflow`
}

// Mirrors is_convertible_to_broadcast in the backend, except the exit condition, which the note asks the agent to fix
// first. A flow the endpoint would refuse for any other reason gets no note.
function isConvertibleShape(flow: HogFlowLike): boolean {
    if (flow.origin_product || flow.status === 'archived' || flow.draft) {
        return false
    }
    const steps = flow.actions ?? []
    const trigger = steps.find((step) => step.type === 'trigger')
    const email = steps.find((step) => step.type === 'function_email')
    const exit = steps.find((step) => step.type === 'exit')
    if (steps.length !== 3 || !trigger || !email || !exit) {
        return false
    }
    if (trigger.config?.type !== 'batch' || trigger.config?.filters?.audience_type === 'accounts') {
        return false
    }
    const paths = new Set((flow.edges ?? []).map((edge) => `${edge.from}->${edge.to}`))
    return paths.size === 2 && paths.has(`${trigger.id}->${email.id}`) && paths.has(`${email.id}->${exit.id}`)
}

/** Guidance for an agent that made or fetched a workflow which could be a broadcast, or null when it can't be one. */
export function broadcastConversionNote(flow: HogFlowLike): string | null {
    if (!isConvertibleShape(flow)) {
        return null
    }
    const exitStep =
        flow.exit_condition === 'exit_only_at_end'
            ? ''
            : " Converting needs exit_condition 'exit_only_at_end', so set that with workflows-update first."
    return (
        'This workflow is one email to a batch audience, which is a broadcast. Ask the user whether to move it to ' +
        'broadcasts with workflows-convert-to-broadcast: it then opens in the broadcast editor with per-send ' +
        `delivery, open and click numbers, and can no longer take more steps.${exitStep}`
    )
}
