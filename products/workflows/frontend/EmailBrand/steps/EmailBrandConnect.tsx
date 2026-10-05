import { useActions, useValues } from 'kea'

import { IconGithub } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { useIntegrationManagementRestriction } from 'lib/integrations/integrationPermissions'

import { emailBrandFlowLogic } from '../emailBrandFlowLogic'
import type { EmailBrandFlowProps } from '../emailBrandFlowLogic'

export function EmailBrandConnect(props: EmailBrandFlowProps): JSX.Element {
    const logic = emailBrandFlowLogic(props)
    const { connecting, connectionLoading } = useValues(logic)
    const { connectGitHub, refreshConnection } = useActions(logic)
    const restriction = useIntegrationManagementRestriction()
    return (
        <div className="max-w-lg mx-auto py-8 text-center">
            <h2>Connect GitHub to find your brand</h2>
            <p>
                PostHog reads your app's manifest, theme files and logo images to find your name, colors and font.
                Detection only reads files. It does not change your repository.
            </p>
            <LemonButton
                type="primary"
                icon={<IconGithub />}
                onClick={connectGitHub}
                loading={connecting}
                disabledReason={restriction}
                center
                fullWidth
                data-attr="email-brand-connect-github"
            >
                Connect GitHub
            </LemonButton>
            <LemonButton
                type="tertiary"
                onClick={refreshConnection}
                loading={connectionLoading}
                center
                fullWidth
                className="mt-2"
                data-attr="email-brand-check-connection"
            >
                I've connected GitHub
            </LemonButton>
        </div>
    )
}
