import { IconCreditCard } from '@posthog/icons'
import { Tooltip, TooltipContent, TooltipTrigger } from '@posthog/quill-primitives'

export interface ComposerBillingIndicatorProps {
    ownPlan: boolean
    locked?: boolean
}

export function ComposerBillingIndicator({ ownPlan, locked = false }: ComposerBillingIndicatorProps): JSX.Element {
    const label = ownPlan ? 'ChatGPT plan' : 'PostHog credits'
    return (
        <Tooltip>
            <TooltipTrigger
                render={
                    <span
                        tabIndex={0}
                        className="flex items-center gap-1 rounded px-1 text-xs text-muted-foreground"
                        data-attr="composer-billing-indicator"
                    >
                        <IconCreditCard className="shrink-0" />
                        <span className="@max-[480px]/composer:hidden">{label}</span>
                    </span>
                }
            />
            <TooltipContent>
                {locked
                    ? `This run uses ${ownPlan ? 'your ChatGPT plan' : 'PostHog credits'}. Billing cannot change during a run.`
                    : ownPlan
                      ? 'This chat uses your ChatGPT plan. Change it in the model menu.'
                      : 'This chat uses your PostHog credits.'}
            </TooltipContent>
        </Tooltip>
    )
}
