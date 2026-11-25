import { IconCheckCircle } from '@posthog/icons'
import { LemonTag, Tooltip } from '@posthog/lemon-ui'

export function KeptResolvedPill(): JSX.Element {
    return (
        <Tooltip title="This exception came from a release the issue was already seen in, or an older one, so the issue stayed resolved.">
            <LemonTag
                className="gap-1.5 bg-fill-primary cursor-default"
                data-attr="error-tracking-exception-kept-resolved"
            >
                <IconCheckCircle />
                Didn't reopen: older release
            </LemonTag>
        </Tooltip>
    )
}
