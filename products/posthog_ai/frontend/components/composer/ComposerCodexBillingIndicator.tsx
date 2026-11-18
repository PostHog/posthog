import { useActions, useValues } from 'kea'
import { useId } from 'react'

import { IconCreditCard } from '@posthog/icons'
import {
    Button,
    DropdownMenu,
    DropdownMenuContent,
    DropdownMenuItem,
    DropdownMenuRadioGroup,
    DropdownMenuRadioItem,
    DropdownMenuSeparator,
    DropdownMenuTrigger,
} from '@posthog/quill'

import { CodexConnectModal } from 'scenes/settings/user/CodexConnectModal'
import { personalCodexIntegrationLogic } from 'scenes/settings/user/personalCodexIntegrationLogic'

import { CodexIntegrationStatusEnumApi } from '~/generated/core/api.schemas'

import { ModelAccessEnumApi } from 'products/tasks/frontend/generated/api.schemas'

import { codexBillingLogic } from '../../logics/codexBillingLogic'
import { ComposerBillingIndicator } from './ComposerBillingIndicator'

export interface ComposerCodexBillingIndicatorProps {
    lockedCodexModelAccess?: string | null
}

export function ComposerCodexBillingIndicator({
    lockedCodexModelAccess,
}: ComposerCodexBillingIndicatorProps): JSX.Element {
    const { effectiveCodexModelAccess, planConnected, codexIntegration } = useValues(codexBillingLogic)
    const { setPreferredCodexModelAccess, connectPlan } = useActions(codexBillingLogic)
    const { codexIntegrationLoadFailed, codexIntegrationLoading } = useValues(personalCodexIntegrationLogic)
    const { loadCodexIntegration } = useActions(personalCodexIntegrationLogic)
    const opener = `billing:${useId()}`
    const access = lockedCodexModelAccess ?? effectiveCodexModelAccess
    const ownPlan = access === ModelAccessEnumApi.OwnSubscription

    if (lockedCodexModelAccess != null) {
        return <ComposerBillingIndicator ownPlan={ownPlan} locked />
    }

    const reauthRequired = codexIntegration?.status === CodexIntegrationStatusEnumApi.ReauthRequired
    const loading = codexIntegration === null && !codexIntegrationLoadFailed
    const label = loading ? 'Loading billing…' : ownPlan ? 'ChatGPT plan' : 'PostHog credits'

    return (
        <>
            <DropdownMenu>
                <DropdownMenuTrigger
                    render={
                        <Button
                            variant="default"
                            size="sm"
                            className="text-xs text-muted-foreground"
                            disabled={loading}
                            aria-label={`Change billing: ${label}`}
                            data-attr="composer-billing-indicator"
                        >
                            <IconCreditCard className="shrink-0" />
                            <span className="@max-[480px]/composer:hidden">{label}</span>
                        </Button>
                    }
                />
                <DropdownMenuContent align="end">
                    <DropdownMenuRadioGroup
                        value={access}
                        onValueChange={(value) => setPreferredCodexModelAccess(value as ModelAccessEnumApi)}
                    >
                        <DropdownMenuRadioItem value={ModelAccessEnumApi.PosthogGateway} closeOnClick>
                            PostHog credits
                        </DropdownMenuRadioItem>
                        <DropdownMenuRadioItem
                            value={ModelAccessEnumApi.OwnSubscription}
                            disabled={!planConnected}
                            closeOnClick
                        >
                            OpenAI (ChatGPT plan)
                        </DropdownMenuRadioItem>
                    </DropdownMenuRadioGroup>
                    {!planConnected && (
                        <>
                            <DropdownMenuSeparator />
                            {codexIntegrationLoadFailed ? (
                                <DropdownMenuItem
                                    disabled={codexIntegrationLoading}
                                    onClick={() => loadCodexIntegration()}
                                >
                                    Could not load your connection. Try again.
                                </DropdownMenuItem>
                            ) : (
                                <DropdownMenuItem
                                    onClick={() => connectPlan(opener)}
                                    data-attr="composer-codex-connect-plan"
                                >
                                    {reauthRequired ? 'Reconnect your ChatGPT account' : 'Connect your ChatGPT account'}
                                </DropdownMenuItem>
                            )}
                        </>
                    )}
                </DropdownMenuContent>
            </DropdownMenu>
            <CodexConnectModal opener={opener} />
        </>
    )
}
