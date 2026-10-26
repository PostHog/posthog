import { useValues } from 'kea'

import { ModelAccessEnumApi } from 'products/tasks/frontend/generated/api.schemas'

import { codexBillingLogic } from '../../logics/codexBillingLogic'
import { ComposerBillingIndicator } from './ComposerBillingIndicator'

export function ComposerCodexBillingIndicator(): JSX.Element {
    const { effectiveCodexModelAccess } = useValues(codexBillingLogic)
    return <ComposerBillingIndicator ownPlan={effectiveCodexModelAccess === ModelAccessEnumApi.OwnSubscription} />
}
