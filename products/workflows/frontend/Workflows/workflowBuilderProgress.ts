import { objectsEqual } from 'lib/utils/objects'

import type { HogFlow, HogFlowAction, HogFlowActionValidationResult } from './hogflows/types'
import type { WorkflowLogicProps } from './workflowLogic'

export type WorkflowStartPath = 'template' | 'prefilled' | 'blank' | 'existing'

export type WorkflowBuilderEdit = 'trigger' | 'step_added' | 'step_edited' | 'none'

export type ValidationById = Record<string, HogFlowActionValidationResult | null>

export function workflowStartPath(props: WorkflowLogicProps): WorkflowStartPath {
    if (props.id && props.id !== 'new') {
        return 'existing'
    }
    if (props.templateId) {
        return 'template'
    }
    return props.triggerPrefill ? 'prefilled' : 'blank'
}

function isStep(action: HogFlowAction): boolean {
    return action.type !== 'trigger' && action.type !== 'exit'
}

function triggerOf(workflow: HogFlow): HogFlowAction | undefined {
    return workflow.actions.find((action) => action.type === 'trigger')
}

function stepKind(action: HogFlowAction): string {
    return action.type === 'function' ? `function:${action.config.template_id}` : action.type
}

function countBy(values: string[]): Record<string, number> {
    const counts: Record<string, number> = {}
    for (const value of values) {
        counts[value] = (counts[value] ?? 0) + 1
    }
    return counts
}

function branchCount(workflow: HogFlow): number {
    const outgoing = countBy(workflow.edges.map((edge) => edge.from))
    return Object.values(outgoing).filter((count) => count > 1).length
}

function isValid(action: HogFlowAction, validationById: ValidationById): boolean {
    return validationById[action.id]?.valid ?? true
}

export interface BuilderProgress {
    trigger_type: string | null
    trigger_valid: boolean
    step_count: number
    invalid_step_count: number
    invalid_step_types: string[]
    step_types: Record<string, number>
    branch_count: number
}

export function builderProgress(workflow: HogFlow, validationById: ValidationById): BuilderProgress {
    const trigger = triggerOf(workflow)
    const steps = workflow.actions.filter(isStep)
    const invalidSteps = steps.filter((step) => !isValid(step, validationById))
    return {
        trigger_type: trigger?.type === 'trigger' ? (trigger.config.type ?? null) : null,
        trigger_valid: !!trigger && isValid(trigger, validationById),
        step_count: steps.length,
        invalid_step_count: invalidSteps.length,
        invalid_step_types: [...new Set(invalidSteps.map(stepKind))],
        step_types: countBy(steps.map(stepKind)),
        branch_count: branchCount(workflow),
    }
}

export function classifyEdit(before: HogFlow, after: HogFlow): WorkflowBuilderEdit | null {
    if (after.actions.filter(isStep).length > before.actions.filter(isStep).length) {
        return 'step_added'
    }
    if (!objectsEqual(triggerOf(before)?.config, triggerOf(after)?.config)) {
        return 'trigger'
    }
    return objectsEqual(before.actions, after.actions) && objectsEqual(before.edges, after.edges) ? null : 'step_edited'
}

export function addedStepKind(before: HogFlow, after: HogFlow): string | null {
    const existingIds = new Set(before.actions.map((action) => action.id))
    const added = after.actions.find((action) => isStep(action) && !existingIds.has(action.id))
    return added ? stepKind(added) : null
}
