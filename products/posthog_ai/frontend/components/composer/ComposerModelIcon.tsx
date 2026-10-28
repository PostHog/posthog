import { IconLogomark } from '@posthog/icons'

import { AnthropicLogo } from 'scenes/onboarding/shared/logos/AnthropicLogo'
import { OpenAILogo } from 'scenes/onboarding/shared/logos/OpenAILogo'

export interface ComposerModelIconProps {
    model: string
    ownPlan: boolean
}

/** Shows who pays for the run: the provider's logo for the user's own plan, the PostHog logo for PostHog credits. */
export function ComposerModelIcon({ model, ownPlan }: ComposerModelIconProps): JSX.Element {
    const PlanLogo = !ownPlan
        ? null
        : model.startsWith('gpt-')
          ? OpenAILogo
          : model.startsWith('claude-')
            ? AnthropicLogo
            : null
    return (
        <span
            className="inline-flex size-3.5 shrink-0 items-center justify-center [&_svg]:size-full"
            title={ownPlan ? 'Billed to your plan' : 'Billed to PostHog credits'}
        >
            {PlanLogo ? <PlanLogo /> : <IconLogomark />}
        </span>
    )
}
