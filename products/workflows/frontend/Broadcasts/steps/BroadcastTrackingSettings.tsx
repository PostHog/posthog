import { LemonSwitch } from '@posthog/lemon-ui'

import { RunLinkTagHint } from '../../Workflows/hogflows/steps/components/RunLinkTagHint'

export function BroadcastTrackingSettings({
    trackingEnabled,
    utmTagsEnabled,
    onChange,
}: {
    trackingEnabled: boolean
    utmTagsEnabled: boolean
    onChange: (settings: { trackingEnabled?: boolean; utmTagsEnabled?: boolean }) => void
}): JSX.Element {
    return (
        <>
            <div className="flex flex-wrap gap-2" data-attr="broadcast-tracking-settings">
                <LemonSwitch
                    label="Track opens and link clicks"
                    checked={trackingEnabled}
                    onChange={(checked) => onChange({ trackingEnabled: checked })}
                    bordered
                    data-attr="broadcast-tracking-toggle"
                />
                <LemonSwitch
                    label="Add UTM tags to links"
                    checked={utmTagsEnabled}
                    onChange={(checked) => onChange({ utmTagsEnabled: checked })}
                    bordered
                    data-attr="broadcast-utm-tags-toggle"
                />
            </div>
            {trackingEnabled ? (
                <RunLinkTagHint />
            ) : (
                <span className="text-xs text-secondary">
                    Links stay as written and no tracking pixel is added, so this broadcast shows no opens or clicks.
                </span>
            )}
        </>
    )
}
