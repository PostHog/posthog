import { LemonSwitch } from '@posthog/lemon-ui'

import { RunLinkTagHint } from '../../Workflows/hogflows/steps/components/RunLinkTagHint'

export function BroadcastTrackingSwitch({
    checked,
    onChange,
}: {
    checked: boolean
    onChange: (checked: boolean) => void
}): JSX.Element {
    return (
        <>
            <LemonSwitch
                label="Track opens and link clicks"
                checked={checked}
                onChange={onChange}
                bordered
                data-attr="broadcast-tracking-toggle"
            />
            {checked ? (
                <RunLinkTagHint />
            ) : (
                <span className="text-xs text-secondary">
                    Links stay as written and no tracking pixel is added, so this broadcast shows no opens or clicks.
                </span>
            )}
        </>
    )
}
