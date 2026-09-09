import { FeatureFlagKey } from 'lib/constants'

import { CreateActionType } from '../../hogFlowEditorLogic'

export type ActionNodeCategory = {
    label: string
    featureFlag?: FeatureFlagKey
    nodes: CreateActionType[]
}

const registeredCategories: ActionNodeCategory[] = []
// Nodes the toolbar renders by hand (flag-gated, outside a category) but that still take part
// in template lookups such as output mapping suggestions.
const standaloneNodes: CreateActionType[] = []

export function registerActionNodeCategory(category: ActionNodeCategory): void {
    registeredCategories.push(category)
}

export function registerStandaloneActionNode(node: CreateActionType): void {
    standaloneNodes.push(node)
}

export function getRegisteredActionNodeCategories(): ActionNodeCategory[] {
    return registeredCategories
}

export function getRegisteredActionNodes(): CreateActionType[] {
    return [...registeredCategories.flatMap((category) => category.nodes), ...standaloneNodes]
}
