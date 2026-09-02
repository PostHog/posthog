import { IconBolt, IconCompass } from '@posthog/icons'
import { Spinner } from '@posthog/lemon-ui'

export function InstallingFlowRow({ type }: { type: 'source' | 'scout' }): JSX.Element {
    const Icon = type === 'source' ? IconBolt : IconCompass
    const title = type === 'source' ? 'Connecting sources' : 'Creating scheduled scouts'
    const description =
        type === 'source'
            ? 'The setup agent is choosing and connecting signal sources.'
            : 'The setup agent is creating scouts for this project.'

    return (
        <div className="grid grid-cols-[2rem_minmax(0,1fr)_auto] items-center gap-3 border-b border-primary px-1 py-3 last:border-b-0">
            <div className="relative flex size-8 items-center justify-center rounded-full border border-primary bg-bg-light text-tertiary">
                <Icon />
                <span
                    className="absolute -right-0.5 -top-0.5 size-2.5 rounded-full border-2 border-bg-light bg-warning motion-safe:animate-pulse"
                    aria-hidden
                />
            </div>
            <div className="min-w-0">
                <div className="text-sm font-medium">{title}</div>
                <div className="mt-0.5 text-xs text-tertiary">{description}</div>
            </div>
            <Spinner className="text-sm text-warning" />
        </div>
    )
}
