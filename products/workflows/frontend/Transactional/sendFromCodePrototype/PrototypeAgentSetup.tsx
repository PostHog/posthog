// PROTOTYPE (ticket #320), throwaway: the agent path, shown beside the snippet in every variant.
import { CodeSnippet, Language } from 'lib/components/CodeSnippet'

export function PrototypeAgentSetup(): JSX.Element {
    return (
        <div className="flex flex-col gap-3 min-w-0">
            <div className="flex flex-col gap-1">
                <h4 className="m-0 text-sm font-semibold">Let the Wizard set it up</h4>
                <p className="m-0 text-secondary text-sm">
                    Run it in your app's folder. The setup agent finds your verified sender, adds the API key to your
                    env file and writes your first send.
                </p>
                <CodeSnippet language={Language.Bash} compact wrap thing="Wizard command">
                    npx @posthog/wizard transactional-email
                </CodeSnippet>
            </div>
            <div className="flex flex-col gap-1">
                <h4 className="m-0 text-sm font-semibold">Moving from SendGrid or Resend?</h4>
                <p className="m-0 text-secondary text-sm">
                    The setup agent swaps your provider's send calls for PostHog's and keeps your templates in code.
                </p>
                <CodeSnippet language={Language.Bash} compact wrap thing="Wizard command">
                    npx @posthog/wizard migrate-email
                </CodeSnippet>
            </div>
        </div>
    )
}
