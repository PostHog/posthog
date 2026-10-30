import { useValues } from 'kea'
import posthog from 'posthog-js'
import { useState } from 'react'

import { LemonSegmentedButton, Link } from '@posthog/lemon-ui'

import { CodeSnippet, Language } from 'lib/components/CodeSnippet'
import { apiHostOrigin } from 'lib/utils/apiHost'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'

type SnippetLanguage = 'node' | 'python' | 'curl'

const LANGUAGE_OPTIONS: { value: SnippetLanguage; label: string; 'data-attr': string }[] = [
    { value: 'node', label: 'Node.js', 'data-attr': 'transactional-email-api-example-node' },
    { value: 'python', label: 'Python', 'data-attr': 'transactional-email-api-example-python' },
    { value: 'curl', label: 'curl', 'data-attr': 'transactional-email-api-example-curl' },
]

const INSTALL_COMMANDS: Partial<Record<SnippetLanguage, string>> = {
    node: 'npm install posthog-node@^5.61.0',
    python: 'pip install "posthog>=7.81.0"',
}

export function TransactionalEmailApiExample({
    templateId,
    variables,
}: {
    templateId: string
    /** The email's `{{ variables.* }}` names. The snippet shows a sample when the email uses none. */
    variables?: string[]
}): JSX.Element {
    const { currentTeam, currentTeamIdStrict } = useValues(teamLogic)
    const [language, setLanguage] = useState<SnippetLanguage>('node')

    const projectToken = currentTeam?.api_token ?? '<ph_project_api_key>'
    const host = apiHostOrigin()
    // The SDKs find the app host themselves only on PostHog Cloud, where the ingestion host differs from the app's.
    const appHost = host === window.location.origin ? host : null
    const data: [string, string][] = variables?.length
        ? variables.map((name) => [name, '...'])
        : [
              ['first_name', 'Jane'],
              ['reset_link', 'https://example.com/reset'],
          ]
    const dataEntries = (separator: string): string =>
        data.map(([name, value]) => `"${name}"${separator}"${value}"`).join(', ')

    const snippets: Record<SnippetLanguage, { language: Language; code: string }> = {
        node: {
            language: Language.JavaScript,
            code: `import { PostHog } from 'posthog-node'

const posthog = new PostHog('${projectToken}', {
    host: '${host}',${appHost ? `\n    appHost: '${appHost}',` : ''}
    secretKey: process.env.POSTHOG_PROJECT_SECRET_API_KEY,
    // This client only sends email, so it doesn't poll flag definitions with the secret key
    enableLocalEvaluation: false,
})

const { data, error } = await posthog.emails.send({
    to: 'jane@example.com',
    templateId: '${templateId}',
    templateData: { ${dataEntries(': ')} },
    distinctId: 'jane-distinct-id',
    idempotencyKey: 'password-reset-123',
})
if (error) {
    throw error
}
console.log(data.id)`,
        },
        python: {
            language: Language.Python,
            code: `import os

from posthog import Posthog

posthog = Posthog(
    "${projectToken}",
    host="${host}",${appHost ? `\n    app_host="${appHost}",` : ''}
    secret_key=os.environ["POSTHOG_PROJECT_SECRET_API_KEY"],
)

result = posthog.emails.send(
    to="jane@example.com",
    template_id="${templateId}",
    template_data={${dataEntries(': ')}},
    distinct_id="jane-distinct-id",
    idempotency_key="password-reset-123",
)
print(result.id)`,
        },
        curl: {
            language: Language.Bash,
            code: `curl -X POST ${window.location.origin}/api/projects/${currentTeamIdStrict}/messaging/send/email/ \\
  -H "Authorization: Bearer $POSTHOG_PROJECT_SECRET_API_KEY" \\
  -H "Content-Type: application/json" \\
  -H "Idempotency-Key: password-reset-123" \\
  -d '{
    "template": { "id": "${templateId}" },
    "to": "jane@example.com",
    "identifiers": { "distinct_id": "jane-distinct-id" },
    "message_data": { ${dataEntries(': ')} }
  }'`,
        },
    }
    const snippet = snippets[language]
    const installCommand = INSTALL_COMMANDS[language]

    return (
        <div className="flex flex-col gap-4 max-w-200" data-attr="transactional-email-api-example">
            <p className="mb-0">
                Send this email from your code. Each send runs once and shows up under Metrics and Sends, and on the
                recipient's person.
            </p>
            <ul className="list-disc pl-6 mb-0 flex flex-col gap-1">
                <li>
                    Authenticate with a{' '}
                    <Link to={urls.settings('environment-secret-api-keys')}>project secret API key</Link> that has the{' '}
                    <code>hog_flow:write</code> scope. Keep it on your server in{' '}
                    <code>POSTHOG_PROJECT_SECRET_API_KEY</code>.
                </li>
                <li>
                    The template data fills the template's <code>{'{{ variables.* }}'}</code> placeholders. The template
                    can't read person properties, so pass everything it needs here.
                </li>
                <li>
                    The distinct ID is the person the send is recorded against. Leave it out and the recipient's email
                    address is used.
                </li>
                <li>
                    The idempotency key makes a retry safe. A send with the same key within 24 hours returns the first
                    send's message ID instead of sending the email again.
                </li>
            </ul>
            <LemonSegmentedButton
                size="small"
                value={language}
                onChange={setLanguage}
                options={LANGUAGE_OPTIONS}
            />
            {installCommand ? (
                <CodeSnippet language={Language.Bash} compact thing="install command">
                    {installCommand}
                </CodeSnippet>
            ) : null}
            <CodeSnippet
                language={snippet.language}
                thing="code"
                onCopy={() => posthog.capture('transactional email snippet copied', { language })}
            >
                {snippet.code}
            </CodeSnippet>
        </div>
    )
}
