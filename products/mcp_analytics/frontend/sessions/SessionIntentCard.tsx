import { IconSparkles } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'
import { Skeleton } from '@posthog/quill-primitives'

import { AccessControlAction } from 'lib/components/AccessControlAction'
import { cn } from 'lib/utils/css-classes'

import { AccessControlLevel, AccessControlResourceType } from '~/types'

const PLACEHOLDER_WIDTHS = ['w-11/12', 'w-2/3']

/** The session's intent in the header. Before it's summarized, a cutout marks where it will go. */
export function SessionIntentCard({
    intent,
    isGenerating,
    onGenerate,
}: {
    intent: string
    isGenerating: boolean
    onGenerate: () => void
}): JSX.Element {
    if (intent) {
        return (
            <div className="flex gap-2" data-attr="mcp-session-intent-card">
                <IconSparkles className="mt-0.5 shrink-0 text-accent" />
                <div className="flex min-w-0 flex-col gap-0.5">
                    <span className="text-xs font-semibold text-accent">Session intent</span>
                    <p className="m-0 text-sm leading-snug">{intent}</p>
                </div>
            </div>
        )
    }
    return (
        <div
            className="flex items-center gap-3 rounded-md border border-dashed border-accent/50 bg-accent/5 px-3 py-2"
            data-attr="mcp-session-intent-card"
        >
            <IconSparkles className="shrink-0 text-accent" />
            <div className="flex min-w-0 flex-1 flex-col gap-1.5">
                <span className="text-xs font-semibold text-accent">Session intent</span>
                <div className="flex flex-col gap-1.5" aria-hidden>
                    {PLACEHOLDER_WIDTHS.map((width) =>
                        isGenerating ? (
                            <Skeleton key={width} className={cn('h-2', width)} />
                        ) : (
                            <div key={width} className={cn('h-2 rounded bg-accent/15', width)} />
                        )
                    )}
                </div>
            </div>
            <AccessControlAction
                resourceType={AccessControlResourceType.McpAnalytics}
                minAccessLevel={AccessControlLevel.Editor}
            >
                <LemonButton
                    type="primary"
                    size="small"
                    icon={<IconSparkles />}
                    loading={isGenerating}
                    onClick={onGenerate}
                    className="shrink-0"
                    data-attr="mcp-session-summarize-intent"
                >
                    {isGenerating ? 'Summarizing…' : 'Summarize intent'}
                </LemonButton>
            </AccessControlAction>
        </div>
    )
}
