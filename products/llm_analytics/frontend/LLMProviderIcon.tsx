import { AnthropicLogo } from 'scenes/onboarding/sdks/logos/AnthropicLogo'
import geminiImage from 'scenes/onboarding/sdks/logos/gemini.svg'
import { OpenAILogo } from 'scenes/onboarding/sdks/logos/OpenAILogo'
import { OpenRouterLogo } from 'scenes/onboarding/sdks/logos/OpenRouterLogo'

import { LLMProvider, LLM_PROVIDER_LABELS } from './settings/llmProviderKeysLogic'

const PROVIDER_IMAGES: Partial<Record<LLMProvider, string>> = {
    gemini: geminiImage,
    fireworks: 'https://res.cloudinary.com/dmukukwp6/image/upload/fireworks_ai_a3d8a59e96.svg',
}

const PROVIDER_COMPONENTS: Partial<Record<LLMProvider, React.ComponentType>> = {
    openai: OpenAILogo,
    openrouter: OpenRouterLogo,
    anthropic: AnthropicLogo,
}

export function LLMProviderIcon({
    provider,
    className = 'size-4',
}: {
    provider: LLMProvider
    className?: string
}): JSX.Element | null {
    const imageUrl = PROVIDER_IMAGES[provider]
    if (imageUrl) {
        return <img src={imageUrl} className={className} alt={provider} />
    }

    const Component = PROVIDER_COMPONENTS[provider]
    if (Component) {
        return (
            <span className={`${className} inline-flex items-center justify-center overflow-hidden`}>
                <Component />
            </span>
        )
    }

    return null
}

export const LLM_PROVIDER_SELECT_OPTIONS = (Object.keys(LLM_PROVIDER_LABELS) as LLMProvider[]).map((provider) => ({
    value: provider,
    label: LLM_PROVIDER_LABELS[provider],
    icon: <LLMProviderIcon provider={provider} />,
}))
