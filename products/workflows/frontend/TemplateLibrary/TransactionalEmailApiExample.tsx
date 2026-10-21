import { useValues } from 'kea'

import { Link } from '@posthog/lemon-ui'

import { CodeSnippet, Language } from 'lib/components/CodeSnippet'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'

export function TransactionalEmailApiExample({ templateId }: { templateId: string }): JSX.Element {
    const { currentTeamIdStrict } = useValues(teamLogic)
    const snippet = `curl -X POST ${window.location.origin}/api/projects/${currentTeamIdStrict}/messaging_templates/${templateId}/send/ \\
  -H "Authorization: Bearer $POSTHOG_PROJECT_SECRET_API_KEY" \\
  -H "Content-Type: application/json" \\
  -d '{
    "to": "jane@example.com",
    "identifiers": { "distinct_id": "jane-distinct-id" },
    "message_data": { "first_name": "Jane", "reset_link": "https://example.com/reset" }
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
                    <code>message_data</code> fills the template's <code>{'{{ variables.* }}'}</code> placeholders. The
                    template can't read person properties, so pass everything it needs here.
                </li>
                <li>
                    <code>identifiers.distinct_id</code> is the person the send is recorded against. Leave it out and
                    the recipient's email address is used.
                </li>
            </ul>
            <CodeSnippet language={Language.Bash}>{snippet}</CodeSnippet>
        </div>
    )
}
