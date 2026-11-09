import { useValues } from 'kea'

import { CodeSnippet, Language } from 'lib/components/CodeSnippet'
import { teamLogic } from 'scenes/teamLogic'

export function CodeEmailApiExample({ templateKey }: { templateKey: string }): JSX.Element {
    const { currentTeamIdStrict } = useValues(teamLogic)
    return (
        <div className="flex flex-col gap-2 max-w-200" data-attr="code-email-api-example">
            <p className="m-0">
                Every send with the key <code>{templateKey}</code> lands on this email. Your code sends the subject and
                the content each time.
            </p>
            <CodeSnippet language={Language.Bash} thing="code">
                {`curl -X POST ${window.location.origin}/api/projects/${currentTeamIdStrict}/messaging/send/email/ \\
  -H "Authorization: Bearer $POSTHOG_PROJECT_SECRET_API_KEY" \\
  -H "Content-Type: application/json" \\
  -d '{
    "template_key": "${templateKey}",
    "to": "jane@example.com",
    "distinct_id": "jane-distinct-id",
    "subject": "Your subject",
    "html": "<p>Your content</p>"
  }'`}
            </CodeSnippet>
        </div>
    )
}
