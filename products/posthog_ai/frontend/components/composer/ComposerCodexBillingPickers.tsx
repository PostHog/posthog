import { useActions, useValues } from 'kea'
import { useId } from 'react'

import { CodexConnectModal } from 'scenes/settings/user/CodexConnectModal'

import { ModelAccessEnumApi } from 'products/tasks/frontend/generated/api.schemas'

import { codexBillingLogic } from '../../logics/codexBillingLogic'
import { ComposerModelEffortPickers, type ComposerModelEffortPickersProps } from './ComposerModelEffortPickers'

export interface ComposerCodexBillingPickersProps extends Omit<ComposerModelEffortPickersProps, 'codexBilling'> {
    /** The billing a live run booted with. A live run can't change it, so the row shows it locked. */
    lockedCodexModelAccess?: string | null
}

/**
 * The model picker plus the Codex billing row. Rendered only behind the rollout flag, so users without the
 * flag never load their ChatGPT connection.
 */
export function ComposerCodexBillingPickers({
    lockedCodexModelAccess,
    ...pickerProps
}: ComposerCodexBillingPickersProps): JSX.Element {
    const { effectiveCodexModelAccess, planConnected } = useValues(codexBillingLogic)
    const { setPreferredCodexModelAccess, connectPlan } = useActions(codexBillingLogic)
    const opener = `composer:${useId()}`
    const locked = lockedCodexModelAccess != null

    return (
        <>
            <ComposerModelEffortPickers
                {...pickerProps}
                codexBilling={{
                    value: locked
                        ? lockedCodexModelAccess === ModelAccessEnumApi.OwnSubscription
                            ? ModelAccessEnumApi.OwnSubscription
                            : ModelAccessEnumApi.PosthogGateway
                        : effectiveCodexModelAccess,
                    planConnected,
                    locked,
                    onChange: setPreferredCodexModelAccess,
                    onConnectPlan: () => connectPlan(opener),
                }}
            />
            <CodexConnectModal opener={opener} />
        </>
    )
}
