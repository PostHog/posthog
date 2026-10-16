import * as mailboxPng from '@posthog/brand/hoggies/png/mailbox'
import { LemonButton } from '@posthog/lemon-ui'

import { pngHoggie } from 'lib/brand/hoggies'

import { ActivityNextSteps } from '../earlyData/ActivityNextSteps'
import { SetupStepHero } from './SetupStepHero'

const HedgehogMailbox = pngHoggie(mailboxPng)

const COPY = {
    title: 'Hear from your server without opening PostHog',
    lead: 'Pick what you want. You can change it later in Notifications.',
    finish: 'Open MCP analytics',
}

export function SetupUsefulStep({ onFinish }: { onFinish: () => void }): JSX.Element {
    return (
        <>
            <SetupStepHero Hedgehog={HedgehogMailbox} title={COPY.title} lead={COPY.lead} />
            <ActivityNextSteps />
            <div className="flex justify-end">
                <LemonButton type="primary" onClick={onFinish} data-attr="mcp-analytics-setup-mode-finish">
                    {COPY.finish}
                </LemonButton>
            </div>
        </>
    )
}
