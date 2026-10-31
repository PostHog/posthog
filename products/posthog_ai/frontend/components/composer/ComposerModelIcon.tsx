import { IconLogomark } from '@posthog/icons'

import { AnthropicLogo } from 'scenes/onboarding/shared/logos/AnthropicLogo'
import { OpenAILogo } from 'scenes/onboarding/shared/logos/OpenAILogo'

import { normalizeModelId } from 'products/tasks/frontend/modelCatalog'

export interface ComposerModelIconProps {
    model: string
    ownPlan: boolean
}

export function ComposerModelIcon({ model, ownPlan }: ComposerModelIconProps): JSX.Element {
    const modelId = normalizeModelId(model)
    const PlanLogo = !ownPlan
        ? null
        : modelId.startsWith('gpt-')
          ? OpenAILogo
          : modelId.startsWith('claude-')
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
