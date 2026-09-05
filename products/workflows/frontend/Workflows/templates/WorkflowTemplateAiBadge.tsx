import { IconSparkles } from '@posthog/icons'

/** Marks a template that hands work to an AI agent. Uses the same purple as AI surfaces elsewhere. */
export function WorkflowTemplateAiBadge(): JSX.Element {
    return (
        <span className="flex items-center gap-1 shrink-0 px-1.5 py-0.5 rounded text-xs font-semibold text-ai bg-ai/10">
            <IconSparkles />
            AI
        </span>
    )
}
