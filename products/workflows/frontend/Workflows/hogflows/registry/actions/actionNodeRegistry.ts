import { FeatureFlagKey } from 'lib/constants'

import { CreateActionType } from '../../hogFlowEditorLogic'

export type ActionNodeCategory = {
    label: string
    featureFlag?: FeatureFlagKey
    nodes: (CreateActionType & { featureFlag?: FeatureFlagKey })[]
}

const registeredCategories: ActionNodeCategory[] = []

export function registerActionNodeCategory(category: ActionNodeCategory): void {
    registeredCategories.push(category)
}

export function getRegisteredActionNodeCategories(featureFlags?: Record<string, unknown>): ActionNodeCategory[] {
    if (!featureFlags) {
        return registeredCategories
    }
    return registeredCategories
        .filter((category) => !category.featureFlag || featureFlags[category.featureFlag])
        .map((category) => ({
            ...category,
            nodes: category.nodes.filter((node) => !node.featureFlag || featureFlags[node.featureFlag]),
        }))
        .filter((category) => category.nodes.length > 0)
}
