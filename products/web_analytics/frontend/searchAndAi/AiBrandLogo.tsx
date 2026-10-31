import clsx from 'clsx'
import { useState } from 'react'

import { claudeLogo, geminiLogo, openaiLogo } from 'lib/components/AgentPromptButton/AgentLogo'
import { faviconUrl } from 'scenes/web-analytics/common'

interface AiBrand {
    pattern: RegExp
    domain: string
    colorClass: string
    logo?: string
    logoFillsTile?: boolean
}

const AI_BRANDS: AiBrand[] = [
    {
        pattern: /chatgpt|openai|gpt|oai-|codex/i,
        domain: 'chatgpt.com',
        colorClass: 'bg-[#10a37f]',
        logo: openaiLogo,
        logoFillsTile: true,
    },
    { pattern: /claude|anthropic/i, domain: 'claude.ai', colorClass: 'bg-[#d97757]', logo: claudeLogo },
    { pattern: /gemini|bard/i, domain: 'gemini.google.com', colorClass: 'bg-[#4285f4]', logo: geminiLogo },
    { pattern: /google|notebooklm/i, domain: 'google.com', colorClass: 'bg-[#4285f4]' },
    {
        pattern: /mistral/i,
        domain: 'chat.mistral.ai',
        colorClass: 'bg-[#fa520f]',
        logo: '/static/services/mistral_ai.svg',
    },
    { pattern: /perplexity/i, domain: 'perplexity.ai', colorClass: 'bg-[#20808d]' },
    { pattern: /copilot|bing|azure|microsoft/i, domain: 'copilot.microsoft.com', colorClass: 'bg-[#0078d4]' },
    { pattern: /grok|xai/i, domain: 'grok.com', colorClass: 'bg-[#111111]' },
    { pattern: /meta/i, domain: 'meta.ai', colorClass: 'bg-[#0866ff]' },
    { pattern: /deepseek/i, domain: 'chat.deepseek.com', colorClass: 'bg-[#4d6bfe]' },
    { pattern: /bytedance|bytespider|tiktok|doubao/i, domain: 'bytedance.com', colorClass: 'bg-[#325ab4]' },
    { pattern: /common ?crawl|ccbot/i, domain: 'commoncrawl.org', colorClass: 'bg-[#2f4b7c]' },
    { pattern: /cohere/i, domain: 'cohere.com', colorClass: 'bg-[#39594d]' },
    { pattern: /diffbot/i, domain: 'diffbot.com', colorClass: 'bg-[#f26522]' },
    { pattern: /amazon|alexa/i, domain: 'amazon.com', colorClass: 'bg-[#ff9900]' },
    { pattern: /apple/i, domain: 'apple.com', colorClass: 'bg-[#555555]' },
    { pattern: /duckassist|duckduck/i, domain: 'duckduckgo.com', colorClass: 'bg-[#de5833]' },
    { pattern: /petal|huawei/i, domain: 'huawei.com', colorClass: 'bg-[#cf0a2c]' },
    { pattern: /kagi/i, domain: 'kagi.com', colorClass: 'bg-[#ffb319]' },
    { pattern: /you\.com|youbot/i, domain: 'you.com', colorClass: 'bg-[#7c3aed]' },
    { pattern: /phind/i, domain: 'phind.com', colorClass: 'bg-[#5a4fcf]' },
    { pattern: /manus/i, domain: 'manus.im', colorClass: 'bg-[#111111]' },
    { pattern: /posthog/i, domain: 'posthog.com', colorClass: 'bg-[#f54e00]' },
]

const NEUTRAL_COLOR_CLASS = 'bg-[var(--color-text-secondary)]'

export function resolveAiBrand(name: string): AiBrand | null {
    return AI_BRANDS.find((brand) => brand.pattern.test(name)) ?? null
}

export type AiBrandLogoSize = 'xs' | 'sm' | 'md'

const BOX_CLASS: Record<AiBrandLogoSize, string> = {
    xs: 'size-4 rounded-sm',
    sm: 'size-5 rounded',
    md: 'size-6 rounded-md',
}

export function AiBrandLogo({ name, size = 'md' }: { name: string; size?: AiBrandLogoSize }): JSX.Element {
    const brand = resolveAiBrand(name)
    const [failed, setFailed] = useState(false)
    const src = brand?.logo ?? (brand ? faviconUrl(brand.domain) : null)
    const boxClass = BOX_CLASS[size]

    if (src && !failed) {
        return (
            <span
                className={clsx(
                    'shrink-0 flex items-center justify-center overflow-hidden bg-white border border-primary',
                    boxClass
                )}
                aria-hidden
            >
                <img
                    src={src}
                    alt=""
                    className={clsx(
                        'object-contain',
                        brand?.logoFillsTile ? 'size-full' : size === 'xs' ? 'size-2.5' : 'size-3.5'
                    )}
                    onError={() => setFailed(true)}
                />
            </span>
        )
    }

    return (
        <span
            className={clsx(
                'shrink-0 flex items-center justify-center font-semibold text-white leading-none',
                size === 'md' ? 'text-xs' : 'text-xxs',
                boxClass,
                brand?.colorClass ?? NEUTRAL_COLOR_CLASS
            )}
            aria-hidden
        >
            {name.trim().charAt(0).toUpperCase() || '?'}
        </span>
    )
}
