import { LemonCard } from '@posthog/lemon-ui'

export const ContentAutopilotPromptsDisabled = (): JSX.Element => (
    <LemonCard hoverEffect={false} className="p-6 text-center">
        <h3 className="m-0">Prompt tracking is not turned on</h3>
        <p className="m-0 mt-2 text-muted max-w-xl mx-auto">
            This project doesn't have access to prompt tracking yet. Ask PostHog support to turn it on.
        </p>
    </LemonCard>
)
