import { waitText } from '../stepFacts'
import type { WaitPresentation } from '../stepPresentation'

function WaitOutcome({ wait }: { wait: WaitPresentation }): JSX.Element {
    const text = waitText(wait)
    switch (wait.kind) {
        case 'condition':
            return (
                <div className="grid grid-cols-[auto_1fr] gap-x-2 gap-y-0.5">
                    <span className="font-semibold text-success">If</span>
                    <span>{wait.name ?? 'the condition'} happens, continue right away</span>
                    <span className="font-semibold text-secondary">Else</span>
                    <span>after {text}, take the other path</span>
                </div>
            )
        case 'date':
            return (
                <div className="text-secondary">
                    {text
                        ? `Everyone waits until ${text}, then continues (${wait.timezone})`
                        : 'Choose a date to wait for'}
                </div>
            )
        case 'duration':
            return (
                <div className="text-secondary">
                    {text ? `Everyone waits ${text}, then continues` : 'Set how long people wait'}
                </div>
            )
    }
}

export function WaitPreview({ wait }: { wait: WaitPresentation }): JSX.Element {
    return (
        <div className="flex flex-col gap-1.5 text-left text-[12.5px]">
            <div className="flex items-center gap-2">
                <span className="size-2 rounded-full bg-[var(--color-text-secondary)]" />
                <span className="h-px flex-1 border-t-2 border-dashed" />
                <span className="rounded-full border px-2 text-[11px] font-semibold">
                    {waitText(wait) ?? 'Not set'}
                </span>
                <span className="h-px flex-1 border-t-2 border-dashed" />
            </div>
            <WaitOutcome wait={wait} />
        </div>
    )
}
