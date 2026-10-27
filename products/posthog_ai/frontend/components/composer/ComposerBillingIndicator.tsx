import { IconCreditCard } from '@posthog/icons'
import { Tooltip, TooltipContent, TooltipTrigger } from '@posthog/quill-primitives'

export interface ComposerBillingIndicatorProps {
    ownPlan: boolean
}

export function ComposerBillingIndicator({ ownPlan }: ComposerBillingIndicatorProps): JSX.Element {
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
                {ownPlan
                    ? 'This chat uses your ChatGPT plan. Change it in the model menu.'
                    : 'This chat uses your PostHog credits.'}
            </TooltipContent>
        </Tooltip>
    )
}
