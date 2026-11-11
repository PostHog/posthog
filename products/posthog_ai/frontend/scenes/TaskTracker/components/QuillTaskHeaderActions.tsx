import { IconExternal, IconGithub, IconPlay } from '@posthog/icons'
import { Button } from '@posthog/quill-primitives'

import { LinkPrimitive } from 'lib/lemon-ui/Link'

export interface QuillTaskHeaderActionsProps {
    /** Link that opens the task in PostHog Desktop, or `null` when the user has no desktop access. */
    desktopUrl: string | null
    prUrl?: string
    /** The run button's label, or `null` when the task cannot run now. */
    runLabel: string | null
    onRun: () => void
    running: boolean
}

export function QuillTaskHeaderActions({
    desktopUrl,
    prUrl,
    runLabel,
    onRun,
    running,
}: QuillTaskHeaderActionsProps): JSX.Element {
    return (
        <div data-quill className="flex flex-wrap items-center gap-1">
            {desktopUrl && (
                <Button
                    variant="outline"
                    nativeButton={false}
                    render={<LinkPrimitive to={desktopUrl} target="_blank" />}
                    className="hidden lg:inline-flex"
                >
                    <IconExternal />
                    Open in PostHog Desktop
                </Button>
            )}
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
