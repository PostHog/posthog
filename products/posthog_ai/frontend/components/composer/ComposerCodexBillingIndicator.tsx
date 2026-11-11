import { useValues } from 'kea'

import { ModelAccessEnumApi } from 'products/tasks/frontend/generated/api.schemas'

import { codexBillingLogic } from '../../logics/codexBillingLogic'
import { ComposerBillingIndicator } from './ComposerBillingIndicator'

export interface ComposerCodexBillingIndicatorProps {
    lockedCodexModelAccess?: string | null
}

export function ComposerCodexBillingIndicator({
    lockedCodexModelAccess,
}: ComposerCodexBillingIndicatorProps): JSX.Element {
    const { effectiveCodexModelAccess } = useValues(codexBillingLogic)
    const access = lockedCodexModelAccess ?? effectiveCodexModelAccess
    return <ComposerBillingIndicator ownPlan={access === ModelAccessEnumApi.OwnSubscription} />
}
