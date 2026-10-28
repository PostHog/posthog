import { IconBrain, IconCheck } from '@posthog/icons'

import { AnthropicLogo } from 'scenes/onboarding/shared/logos/AnthropicLogo'
import { OpenAILogo } from 'scenes/onboarding/shared/logos/OpenAILogo'

export interface ComposerModelIconProps {
    model: string
    ownPlan: boolean
}

export function ComposerModelIcon({ model, ownPlan }: ComposerModelIconProps): JSX.Element {
    const Logo = model.startsWith('gpt-') ? OpenAILogo : model.startsWith('claude-') ? AnthropicLogo : null
    return (
        <span
            className={`relative inline-flex shrink-0 items-center justify-center ${Logo ? 'size-3.5' : 'size-3.5 @max-[299px]/composer:hidden'} ${ownPlan ? 'mr-0.5' : ''}`}
        >
            {Logo ? (
                <span className="inline-flex size-3.5 items-center justify-center [&_svg]:size-full">
                    <Logo />
                </span>
            ) : (
                <IconBrain className="text-muted-foreground @max-[299px]/composer:hidden" />
            )}
            {ownPlan && (
                <span
                    className="absolute -right-1 -bottom-1 flex size-2.5 items-center justify-center rounded-full bg-[#10a37f] text-white ring-[1.5px] ring-[var(--card)]"
                    title="ChatGPT plan"
                >
                    <IconCheck className="size-2" />
                </span>
            )}
        </span>
    )
}
