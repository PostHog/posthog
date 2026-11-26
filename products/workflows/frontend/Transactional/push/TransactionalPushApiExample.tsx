import { useValues } from 'kea'
import posthog from 'posthog-js'

import { Link } from '@posthog/lemon-ui'

import { CodeSnippet, Language } from 'lib/components/CodeSnippet'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'

export function TransactionalPushApiExample({
    templateId,
    variables,
}: {
    templateId: string
    /** The push's `{{ variables.* }}` names. The snippet shows a sample when the push uses none. */
    variables: string[]
}): JSX.Element {
    const { currentTeamIdStrict } = useValues(teamLogic)
    const data = (variables.length ? variables : ['order_id']).map((name) => `"${name}": "..."`).join(', ')

    return (
        <div className="flex flex-col gap-4 max-w-200" data-attr="transactional-push-api-example">
            <p className="mb-0">
                Send this push notification from your server. Each send runs once and shows up under Metrics and Sends.
            </p>
            <ul className="list-disc pl-6 mb-0 flex flex-col gap-1">
                <li>
                    Authenticate with a{' '}
                    <Link to={urls.settings('environment-secret-api-keys')}>project secret API key</Link> that has the{' '}
                    <code>transactional_push:write</code> scope. Keep it on your server in{' '}
                    <code>POSTHOG_PROJECT_SECRET_API_KEY</code>.
                </li>
                <li>
                    The notification goes to every device the person with this distinct ID registered for the chosen
                    apps. A person with no registered device gets nothing, and the send shows as skipped.
                </li>
                <li>
                    The message data fills the template's <code>{'{{ variables.* }}'}</code> placeholders. The template
                    can't read person properties, so pass everything it needs here.
                </li>
                <li>
                    The idempotency key makes a retry safe. A send with the same key within 24 hours returns the first
                    send's message ID instead of sending the notification again.
                </li>
            </ul>
            <CodeSnippet
                language={Language.Bash}
                thing="code"
                onCopy={() => posthog.capture('transactional push snippet copied')}
            >
                {`curl -X POST ${window.location.origin}/api/projects/${currentTeamIdStrict}/messaging/send/push/ \\
  -H "Authorization: Bearer $POSTHOG_PROJECT_SECRET_API_KEY" \\
  -H "Content-Type: application/json" \\
  -H "Idempotency-Key: order-shipped-123" \\
  -d '{
    "template_id": "${templateId}",
    "distinct_id": "jane-distinct-id",
    "message_data": { ${data} }
  }'`}
            </CodeSnippet>
        </div>
    )
}
