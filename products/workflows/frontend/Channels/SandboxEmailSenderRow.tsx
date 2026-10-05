import { useActions } from 'kea'

import { IconLetter, IconPlus } from '@posthog/icons'
import { LemonButton, LemonTag } from '@posthog/lemon-ui'

import { integrationsLogic } from 'lib/integrations/integrationsLogic'

import { IntegrationType } from '~/types'

export function SandboxEmailSenderRow({ integration }: { integration: IntegrationType }): JSX.Element {
    const { openSetupModal } = useActions(integrationsLogic)

    return (
        <div className="rounded border bg-surface-primary p-2 @container" data-attr="sandbox-email-sender">
            <div className="flex flex-col gap-3 ml-2 @lg:flex-row @lg:items-center">
                <div className="flex flex-1 gap-4 items-start min-w-0">
                    <IconLetter className="w-8 h-8 shrink-0" />
                    <div className="flex flex-col gap-1 min-w-0">
                        <div className="flex flex-wrap gap-2 items-center">
                            <strong>Sandbox sender</strong>
                            <LemonTag type="highlight">Sandbox</LemonTag>
                            <span className="text-xs text-secondary truncate">
                                {integration.config.name} &lt;{integration.config.email}&gt;
                            </span>
                        </div>
                        <span className="text-sm text-secondary">
                            Sends from a PostHog address, so it works before you verify a domain. It delivers only to
                            verified members of your organization. Add your own sender to email anyone.
                        </span>
                    </div>
                </div>
                <LemonButton
                    type="secondary"
                    size="small"
                    icon={<IconPlus />}
                    className="shrink-0 self-start @lg:self-center"
                    onClick={() => openSetupModal(undefined, 'email')}
                    data-attr="sandbox-email-sender-add-own"
                >
                    Add your own sender
                </LemonButton>
            </div>
        </div>
    )
}
