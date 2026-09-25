import { useValues } from 'kea'

import * as mailboxPng from '@posthog/brand/hoggies/png/mailbox'
import { LemonButton, LemonCard } from '@posthog/lemon-ui'

import { pngHoggie } from 'lib/brand/hoggies'

import { REPUTATION_DOCS_URL } from './reputationUtils'
import { workflowsReputationActionsLogic } from './workflowsReputationActionsLogic'

const HedgehogMailbox = pngHoggie(mailboxPng)

export function ReputationNoEmailState(): JSX.Element {
    const { tabUrl } = useValues(workflowsReputationActionsLogic)
    return (
        <LemonCard
            hoverEffect={false}
            className="flex flex-col items-center text-center gap-2 px-4 py-10"
            data-attr="workflows-reputation-no-email"
        >
            <HedgehogMailbox className="w-28" />
            <h3 className="mb-0">No email sent yet</h3>
            <p className="text-secondary max-w-120 mb-0">
                Once your workflows send email, this tab shows your bounce and spam complaint rates and what to fix to
                keep them low.
            </p>
            <div className="flex flex-wrap justify-center gap-2 mt-2">
                <LemonButton type="primary" to={tabUrl('channels')} data-attr="workflows-reputation-no-email-channels">
                    Set up an email channel
                </LemonButton>
                <LemonButton
                    type="secondary"
                    to={REPUTATION_DOCS_URL}
                    targetBlank
                    data-attr="workflows-reputation-no-email-docs"
                >
                    How sending reputation works
                </LemonButton>
            </div>
        </LemonCard>
    )
}
