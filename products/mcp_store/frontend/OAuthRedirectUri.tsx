import { useValues } from 'kea'

import { Text } from '@posthog/quill'

import { CopyToClipboardInline } from 'lib/components/CopyToClipboard'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { preflightLogic } from 'lib/logic/preflightLogic'

export function OAuthRedirectUri(): JSX.Element | null {
    const { preflight } = useValues(preflightLogic)
    const todayRailNav = useFeatureFlag('TODAY_RAIL_NAV')

    // The backend builds the redirect URI from SITE_URL, which can differ from the browser origin.
    if (!preflight?.site_url) {
        return null
    }

    if (todayRailNav) {
        return (
            <div className="flex flex-col gap-1">
                <Text size="xs" weight="medium" render={<span className="m-0" />}>
                    Redirect URI
                </Text>
                <Text size="xs" variant="muted" render={<p className="m-0" />}>
                    Add this URI to your OAuth client at the provider.
                </Text>
                <CopyToClipboardInline description="redirect URI" className="font-mono break-all">
                    {`${preflight.site_url}/api/mcp_store/oauth_redirect/`}
                </CopyToClipboardInline>
            </div>
        )
    }

    return (
        <div>
            <div className="font-semibold">Redirect URI</div>
            <p className="text-secondary mb-1">Add this URI to your OAuth client at the provider.</p>
            <CopyToClipboardInline description="redirect URI" className="font-mono break-all">
                {`${preflight.site_url}/api/mcp_store/oauth_redirect/`}
            </CopyToClipboardInline>
        </div>
    )
}
