import { colors } from '@posthog/brand/colors'

import { cn } from 'lib/utils/css-classes'

import { toolNameSize } from '../storyCards'

// Both tiles on a card share one ground, so the badge colour is what tells the good tool from the bad one.
const TONE_COLORS = { good: colors.teal.darker, bad: colors.coral.core } as const

export interface ToolAwardProps {
    label: string
    icon: JSX.Element
    tool: string
    value: string
    unit: string
    detail: string
    tone: 'good' | 'bad'
}

/** One tool singled out on a story card: a badge and label, the tool, its headline number, and a line about it. */
export function ToolAward({ label, icon, tool, value, unit, detail, tone }: ToolAwardProps): JSX.Element {
    return (
        <div className="MCPWrapped__tile MCPWrapped__rise flex flex-col gap-1 rounded-xl px-3 py-2.5">
            <div className="flex items-center gap-1.5 text-xs font-bold">
                <span
                    className="flex size-5 items-center justify-center rounded-full text-white"
                    style={{ background: TONE_COLORS[tone] }}
                >
                    {icon}
                </span>
                {label}
            </div>
            <div className="flex items-end justify-between gap-3">
                <span
                    className={cn(
                        'line-clamp-2 min-w-0 break-all font-mono font-bold',
                        toolNameSize(tool, ['text-base', 'text-sm', 'text-xs'])
                    )}
                    title={tool}
                >
                    {tool}
                </span>
                <span className="shrink-0 text-right leading-none">
                    <span className="block text-xl font-bold tabular-nums">{value}</span>
                    <span className="text-xs opacity-75">{unit}</span>
                </span>
            </div>
            <div className="text-xs opacity-75">{detail}</div>
        </div>
    )
}
