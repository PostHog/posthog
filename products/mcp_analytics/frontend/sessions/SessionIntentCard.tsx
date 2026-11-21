import { IconSparkles } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'
import { Skeleton } from '@posthog/quill-primitives'

import { AccessControlAction } from 'lib/components/AccessControlAction'
import { cn } from 'lib/utils/css-classes'

import { AccessControlLevel, AccessControlResourceType } from '~/types'

const PLACEHOLDER_WIDTHS = ['w-11/12', 'w-2/3']

/** The session's intent in the header. Before it's summarized, an outline of where it will go. */
export function SessionIntentCard({
    intent,
    isGenerating,
    onGenerate,
}: {
    intent: string
    isGenerating: boolean
    onGenerate: () => void
}): JSX.Element {
    return (
        <div
            className={cn(
                'flex flex-col gap-1.5 rounded px-3 py-2',
                intent ? 'bg-accent/10' : 'border border-dashed border-primary'
            )}
            data-attr="mcp-session-intent-card"
        >
            <div className="flex items-center justify-between gap-2">
                <span className="flex items-center gap-1.5 text-xs font-semibold text-accent">
                    <IconSparkles className="shrink-0" />
                    Session intent
                </span>
                {!intent && (
                    <AccessControlAction
                        resourceType={AccessControlResourceType.McpAnalytics}
                        minAccessLevel={AccessControlLevel.Editor}
                    >
                        <LemonButton
                            type="primary"
                            size="xsmall"
                            icon={<IconSparkles />}
                            loading={isGenerating}
                            onClick={onGenerate}
                            data-attr="mcp-session-summarize-intent"
                        >
                            {isGenerating ? 'Summarizing…' : 'Summarize intent'}
                        </LemonButton>
                    </AccessControlAction>
                )}
            </div>
            {intent ? (
                <p className="m-0 text-sm leading-snug">{intent}</p>
            ) : (
                <div className="flex flex-col gap-1.5" aria-hidden>
                    {PLACEHOLDER_WIDTHS.map((width) =>
                        isGenerating ? (
                            <Skeleton key={width} className={cn('h-2.5', width)} />
                        ) : (
                            <div key={width} className={cn('h-2.5 rounded bg-surface-secondary', width)} />
                        )
                    )}
                </div>
            )}
        </div>
    )
}
