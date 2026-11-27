import { IconSparkles } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { AccessControlAction } from 'lib/components/AccessControlAction'

import { AccessControlLevel, AccessControlResourceType } from '~/types'

/** The session's intent in the session footer, or a button to summarize it. */
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
            <div data-attr="mcp-session-intent-card">
                <div className="mb-1.5 flex items-center gap-2">
                    <div className="flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-accent/20 text-accent">
                        <IconSparkles className="text-xs" />
                    </div>
                    <span className="text-[10px] font-semibold uppercase tracking-wider text-accent">
                        Session intent
                    </span>
                </div>
                <p className="ph-no-capture m-0 text-xs leading-relaxed text-default">{intent}</p>
            </div>
        )
    }
    return (
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
                {isGenerating ? 'Thinking…' : 'Summarize session intent'}
            </LemonButton>
        </AccessControlAction>
    )
}
