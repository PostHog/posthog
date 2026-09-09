import { FeatureFlagKey } from 'lib/constants'

import { CreateActionType } from '../../hogFlowEditorLogic'

export type ActionNodeCategory = {
    label: string
    featureFlag?: FeatureFlagKey
    nodes: CreateActionType[]
}

const registeredCategories: ActionNodeCategory[] = []

export function registerActionNodeCategory(category: ActionNodeCategory): void {
    registeredCategories.push(category)
}

export function getRegisteredActionNodeCategories(): ActionNodeCategory[] {
    return registeredCategories
}
