import { useValues } from 'kea'

import { Link } from '@posthog/lemon-ui'

import { CodeSnippet, Language } from 'lib/components/CodeSnippet'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'

function templateReference(templateId: string, templateKey: string | null | undefined): string {
    return templateKey ? `{ "key": "${templateKey}" }` : `{ "id": "${templateId}" }`
}

export function TransactionalEmailApiExample({
    templateId,
    templateKey,
    variables,
}: {
    templateId: string
    templateKey?: string | null
    /** The email's `{{ variables.* }}` names. The snippet shows a sample when the email uses none. */
    variables?: string[]
}): JSX.Element {
    const { currentTeamIdStrict } = useValues(teamLogic)
    const sendsByTemplateKey = useFeatureFlag('WORKFLOWS_EMAIL_FROM_CODE')
    const sentKey = sendsByTemplateKey ? templateKey : null
    const template = templateReference(templateId, sentKey)
    const messageData = variables?.length
        ? `{ ${variables.map((name) => `"${name}": "..."`).join(', ')} }`
        : '{ "first_name": "Jane", "reset_link": "https://example.com/reset" }'
    const snippet = `curl -X POST ${window.location.origin}/api/projects/${currentTeamIdStrict}/messaging/send/email/ \\
  -H "Authorization: Bearer $POSTHOG_PROJECT_SECRET_API_KEY" \\
  -H "Content-Type: application/json" \\
  -H "Idempotency-Key: password-reset-123" \\
  -d '{
    "template": ${template},
    "to": "jane@example.com",
    "identifiers": { "distinct_id": "jane-distinct-id" },
    "message_data": ${messageData}
  }'`

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
                    <code>hog_flow:write</code> scope.
                </li>
                <li>
                    {sentKey ? (
                        <>
                            <code>template.key</code> names this template. The key is the same in every project that has
                            the template.
                        </>
                    ) : (
                        <>
                            <code>template.id</code> names this template in this project.
                        </>
                    )}
                </li>
                <li>
                    <code>message_data</code> fills the template's <code>{'{{ variables.* }}'}</code> placeholders. The
                    template can't read person properties, so pass everything it needs here.
                </li>
                <li>
                    <code>identifiers.distinct_id</code> is the person the send is recorded against. Leave it out and
                    the recipient's email address is used.
                </li>
                <li>
                    <code>Idempotency-Key</code> makes a retry safe. A send with the same key within 24 hours returns
                    the first send's message ID instead of sending the email again.
                </li>
            </ul>
            <CodeSnippet language={Language.Bash}>{snippet}</CodeSnippet>
        </div>
    )
}
