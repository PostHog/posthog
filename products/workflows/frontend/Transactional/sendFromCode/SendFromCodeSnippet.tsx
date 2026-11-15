import { useValues } from 'kea'
import posthog from 'posthog-js'
import { useState } from 'react'

import { LemonSegmentedButton, Link } from '@posthog/lemon-ui'

import { CodeSnippet, Language } from 'lib/components/CodeSnippet'
import { apiHostOrigin } from 'lib/utils/apiHost'
import { getBackendHost } from 'lib/utils/oauthClient'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'

import { SendFromCodeSurface } from './firstCodeSendLogic'
import { SendFromCodeSdk, sendFromCodeSnippet } from './sendFromCodeSnippets'

const SDK_OPTIONS: { value: SendFromCodeSdk; label: string; 'data-attr': string }[] = [
    { value: 'node', label: 'Node.js', 'data-attr': 'send-from-code-snippet-node' },
    { value: 'python', label: 'Python', 'data-attr': 'send-from-code-snippet-python' },
    { value: 'curl', label: 'cURL', 'data-attr': 'send-from-code-snippet-curl' },
]

const LANGUAGES: Record<SendFromCodeSdk, Language> = {
    node: Language.JavaScript,
    python: Language.Python,
    curl: Language.Bash,
}

export function SendFromCodeSnippet({
    from,
    surface,
}: {
    from: string | null
    surface: SendFromCodeSurface
}): JSX.Element {
    const { currentTeam, currentTeamIdStrict } = useValues(teamLogic)
    const [sdk, setSdk] = useState<SendFromCodeSdk>('node')
    // In OAuth mode this app runs against a remote region, which is where the user's server has to send.
    const appOrigin = getBackendHost() ?? window.location.origin
    const host = apiHostOrigin(appOrigin)
    const snippet = sendFromCodeSnippet(sdk, {
        projectToken: currentTeam?.api_token ?? '<ph_project_api_key>',
        host,
        appHost: host === appOrigin ? host : null,
        sendUrl: `${appOrigin}/api/projects/${currentTeamIdStrict}/messaging/send/email/`,
        from,
    })

    return (
        <div className="flex flex-col gap-2 min-w-0" data-attr="send-from-code-snippet">
            <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
                <LemonSegmentedButton size="small" value={sdk} onChange={setSdk} options={SDK_OPTIONS} />
                <span className="text-xs text-secondary">
                    Also PHP, Ruby, Go, .NET, Elixir and Rust.{' '}
                    <Link
                        to="https://posthog.com/docs/workflows/transactional-emails"
                        target="_blank"
                        data-attr="send-from-code-all-sdks"
                    >
                        See all SDKs
                    </Link>
                </span>
            </div>
            {snippet.install ? (
                <CodeSnippet language={Language.Bash} compact thing="install command">
                    {snippet.install}
                </CodeSnippet>
            ) : null}
            <CodeSnippet
                language={LANGUAGES[sdk]}
                thing="code"
                onCopy={() =>
                    // pinned: analytics event name
                    posthog.capture('transactional email snippet copied', { language: sdk, form: 'code', surface })
                }
            >
                {snippet.code}
            </CodeSnippet>
            <p className="m-0 text-xs text-secondary">
                Use a <Link to={urls.settings('environment-secret-api-keys')}>project secret API key</Link> with the{' '}
                <code>transactional_email:write</code> scope, and keep it on your server. The template key names the
                email: each key shows up in Transactional emails with its own metrics.
            </p>
        </div>
    )
}
