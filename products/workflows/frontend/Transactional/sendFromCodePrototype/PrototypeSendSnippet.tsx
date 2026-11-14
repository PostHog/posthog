// PROTOTYPE (ticket #320), throwaway: one snippet that sends an email written in code, no template needed.
import { useValues } from 'kea'
import { useState } from 'react'

import { LemonSegmentedButton, Link } from '@posthog/lemon-ui'

import { CodeSnippet, Language } from 'lib/components/CodeSnippet'
import { apiHostOrigin } from 'lib/utils/apiHost'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'

type Sdk = 'node' | 'python' | 'curl'

const OTHER_SDKS = ['PHP', 'Ruby', 'Go', '.NET', 'Elixir', 'Rust']

export function PrototypeSendSnippet({
    from,
    compact = false,
}: {
    /** A verified sender. Without one the snippet leaves `from` out and the project's default sender is used. */
    from?: string
    compact?: boolean
}): JSX.Element {
    const { currentTeam, currentTeamIdStrict } = useValues(teamLogic)
    const [sdk, setSdk] = useState<Sdk>('node')
    const token = currentTeam?.api_token ?? '<ph_project_api_key>'
    const host = apiHostOrigin()

    const snippets: Record<Sdk, { language: Language; install?: string; code: string }> = {
        node: {
            language: Language.JavaScript,
            install: 'npm install posthog-node',
            code: `import { PostHog } from 'posthog-node'

const posthog = new PostHog('${token}', {
    host: '${host}',
    secretKey: process.env.POSTHOG_PROJECT_SECRET_API_KEY,
})

await posthog.emails.send({
    templateKey: 'welcome',
    to: user.email,
    distinctId: user.id,${from ? `\n    from: '${from}',` : ''}
    subject: 'Welcome to Acme',
    html: '<p>Hi ' + user.name + ', thanks for signing up.</p>',
})`,
        },
        python: {
            language: Language.Python,
            install: 'pip install posthog',
            code: `import os
from posthog import Posthog

posthog = Posthog("${token}", host="${host}", secret_key=os.environ["POSTHOG_PROJECT_SECRET_API_KEY"])

posthog.emails.send(
    template_key="welcome",
    to=user.email,
    distinct_id=user.id,${from ? `\n    from_="${from}",` : ''}
    subject="Welcome to Acme",
    html=f"<p>Hi {user.name}, thanks for signing up.</p>",
)`,
        },
        curl: {
            language: Language.Bash,
            code: `curl -X POST ${window.location.origin}/api/projects/${currentTeamIdStrict}/messaging/send/email/ \\
  -H "Authorization: Bearer $POSTHOG_PROJECT_SECRET_API_KEY" \\
  -H "Content-Type: application/json" \\
  -d '{
    "template_key": "welcome",
    "to": "jane@example.com",
    "distinct_id": "jane-distinct-id",${from ? `\n    "from": "${from}",` : ''}
    "subject": "Welcome to Acme",
    "html": "<p>Hi Jane, thanks for signing up.</p>"
  }'`,
        },
    }
    const snippet = snippets[sdk]

    return (
        <div className="flex flex-col gap-2 min-w-0">
            <div className="flex flex-wrap items-center gap-2">
                <LemonSegmentedButton
                    size="small"
                    value={sdk}
                    onChange={setSdk}
                    options={[
                        { value: 'node', label: 'Node.js' },
                        { value: 'python', label: 'Python' },
                        { value: 'curl', label: 'cURL' },
                    ]}
                />
                <span className="text-xs text-secondary">
                    Also {OTHER_SDKS.join(', ')}.{' '}
                    <Link to="https://posthog.com/docs/workflows" target="_blank">
                        See all SDKs
                    </Link>
                </span>
            </div>
            {snippet.install && !compact ? (
                <CodeSnippet language={Language.Bash} compact thing="install command">
                    {snippet.install}
                </CodeSnippet>
            ) : null}
            <CodeSnippet language={snippet.language} thing="code">
                {snippet.code}
            </CodeSnippet>
            {!compact ? (
                <p className="text-xs text-secondary m-0">
                    Use a <Link to={urls.settings('environment-secret-api-keys')}>project secret API key</Link> with the{' '}
                    <code>transactional_email:write</code> scope. Every send with the same <code>templateKey</code>{' '}
                    groups under one email in this list, with its own metrics.
                </p>
            ) : null}
        </div>
    )
}
