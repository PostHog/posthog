import { useValues } from 'kea'

import { CodeSnippet, Language } from 'lib/components/CodeSnippet'
import { teamLogic } from 'scenes/teamLogic'

export function CodeEmailApiExample({ templateKey }: { templateKey: string }): JSX.Element {
    const { currentTeamIdStrict } = useValues(teamLogic)
    return (
        <div className="flex flex-col gap-2 max-w-200" data-attr="code-email-api-example">
            <p className="m-0">
                Every send with the key <code className="break-all">{templateKey}</code> lands on this email. Your code
                sends the subject and the content each time.
            </p>
            <p className="m-0">
                The idempotency key makes a retry safe. Use a new key for each email, and the same key when you retry
                it. A send with the same key within 24 hours returns the first send's message ID instead of sending the
                email again.
            </p>
            <CodeSnippet language={Language.Bash} thing="code">
                {`curl -X POST ${window.location.origin}/api/projects/${currentTeamIdStrict}/messaging/send/email/ \\
  -H "Authorization: Bearer $POSTHOG_PROJECT_SECRET_API_KEY" \\
  -H "Content-Type: application/json" \\
  -H "Idempotency-Key: unique-send-id-123" \\
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
