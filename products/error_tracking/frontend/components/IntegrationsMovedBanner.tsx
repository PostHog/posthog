import { LemonBanner } from '@posthog/lemon-ui'
import {
    Button,
    Callout,
    CalloutIcon,
    ItemActions,
    ItemContent,
    ItemDescription,
    ItemTitle,
} from '@posthog/quill-primitives'

import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { LinkPrimitive } from 'lib/lemon-ui/Link'
import { urls } from 'scenes/urls'

export function IntegrationsMovedBanner(): JSX.Element {
    const quill = useFeatureFlag('LEMON_UI_TO_QUILL')
    const settingsUrl = urls.settings('environment-error-tracking', 'error-tracking-integrations')

    if (quill) {
        return (
            <Callout tone="info" className="mb-2">
                <CalloutIcon />
                <ItemContent>
                    <ItemTitle>Looking for integrations?</ItemTitle>
                    <ItemDescription>
                        Integrations for connecting error tracking with external services like GitHub or Linear have
                        moved to project settings.
                    </ItemDescription>
                </ItemContent>
                <ItemActions>
                    <Button variant="outline" render={<LinkPrimitive to={settingsUrl} />}>
                        Go to project settings
                    </Button>
                </ItemActions>
            </Callout>
        )
    }

    return (
        <LemonBanner
            type="info"
            className="mb-2"
            action={{
                children: 'Go to project settings',
                to: settingsUrl,
            }}
        >
            <p>
                <strong>Looking for integrations?</strong> Integrations for connecting error tracking with external
                services like GitHub or Linear have moved to project settings.
            </p>
        </LemonBanner>
    )
}
