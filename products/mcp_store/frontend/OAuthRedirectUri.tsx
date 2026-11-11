import { useValues } from 'kea'

import { CopyToClipboardInline } from 'lib/components/CopyToClipboard'
import { preflightLogic } from 'lib/logic/preflightLogic'

export function OAuthRedirectUri(): JSX.Element | null {
    const { preflight } = useValues(preflightLogic)

    // The backend builds the redirect URI from SITE_URL, which can differ from the browser origin.
    if (!preflight?.site_url) {
        return null
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
