import { IconGithub, IconPlay } from '@posthog/icons'
import { Button } from '@posthog/quill-primitives'

export interface QuillTaskHeaderActionsProps {
    prUrl?: string
    /** The run button's label, or `null` when the task cannot run now. */
    runLabel: string | null
    onRun: () => void
    running: boolean
}

export function QuillTaskHeaderActions({ prUrl, runLabel, onRun, running }: QuillTaskHeaderActionsProps): JSX.Element {
    return (
        <div data-quill className="flex flex-wrap items-center gap-1">
            {prUrl && (
                <Button variant="outline" onClick={() => window.open(prUrl, '_blank')}>
                    <IconGithub />
                    View PR
                </Button>
            )}
            {runLabel && (
                <Button variant="primary" onClick={onRun} loading={running}>
                    <IconPlay />
                    {runLabel}
                </Button>
            )}
        </div>
    )
}
