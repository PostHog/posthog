import { type ChartTheme } from '@posthog/quill-charts'

import claudeLogo from '../harness-logos/claude.svg'
import cursorLogo from '../harness-logos/cursor.svg'
import openaiLogo from '../harness-logos/openai.svg'
import vscodeLogo from '../harness-logos/vscode.svg'

interface HarnessLogo {
    src: string
    alt: string
}

export const HARNESS_LOGOS: Record<string, HarnessLogo> = {
    'Claude Code': { src: claudeLogo, alt: 'Claude Code logo' },
    'Claude.ai': { src: claudeLogo, alt: 'Claude.ai logo' },
    'OpenAI Codex': { src: openaiLogo, alt: 'OpenAI Codex logo' },
    Cursor: { src: cursorLogo, alt: 'Cursor logo' },
    'VS Code': { src: vscodeLogo, alt: 'VS Code logo' },
}

// Per-harness slice color (index into the data-viz palette), chosen so the logo drawn on top keeps
// enough contrast against its slice.
const HARNESS_SLICE_COLOR_INDEX: Record<string, number> = {
    'Claude Code': 0,
    'Claude.ai': 2,
    'OpenAI Codex': 1,
    Cursor: 12,
    'VS Code': 11,
}

export function harnessSliceColor(theme: ChartTheme, category: string, fallbackIndex: number): string {
    const index = HARNESS_SLICE_COLOR_INDEX[category] ?? fallbackIndex
    return theme.colors[index % theme.colors.length]
}

// A single harness logo (or a neutral dot when no logo is known for the category).
export function HarnessLogo({
    category,
    className = 'h-4 w-4',
}: {
    category: string
    className?: string
}): JSX.Element {
    const logo = HARNESS_LOGOS[category]
    if (logo) {
        return <img src={logo.src} alt={category} title={category} className={`${className} shrink-0 object-contain`} />
    }
    return <span title={category} className="inline-block h-1.5 w-1.5 shrink-0 rounded-full bg-secondary" aria-hidden />
}

export function HarnessPill({ category, title }: { category: string; title?: string }): JSX.Element {
    return (
        <span
            className="inline-flex max-w-full items-center gap-1.5 rounded-full border border-primary bg-surface-primary px-2 py-0.5 text-xs"
            title={title}
        >
            <HarnessLogo category={category} className="h-3.5 w-3.5" />
            <span className="truncate">{category}</span>
        </span>
    )
}
