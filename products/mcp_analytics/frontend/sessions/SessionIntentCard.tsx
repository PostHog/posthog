import { IconSparkles } from '@posthog/icons'

export function SessionIntentCard({ intent }: { intent: string }): JSX.Element {
    return (
        <div
            className="flex flex-col gap-1 rounded border border-l-2 border-accent bg-accent/10 px-2 py-1.5"
            data-attr="mcp-session-intent-card"
        >
            <div className="flex items-center gap-1.5 text-xs font-semibold text-accent">
                <IconSparkles className="shrink-0 text-xs" />
                Session intent
            </div>
            <p className="m-0 pl-5 text-xs leading-snug text-default">{intent}</p>
        </div>
    )
}
