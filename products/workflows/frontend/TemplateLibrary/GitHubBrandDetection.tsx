import { useValues } from 'kea'
import { router } from 'kea-router'

import { IconGithub } from '@posthog/icons'
import { LemonButton, LemonSkeleton } from '@posthog/lemon-ui'

import api from 'lib/api'
import { resolveTeamGitHubIntegration } from 'lib/integrations/GitHubIntegrationHelpers'
import { integrationsLogic } from 'lib/integrations/integrationsLogic'
import { useIntegrations } from 'scenes/integrations/components/Integration'

import { GitHubRepositoryDetection } from './GitHubRepositoryDetection'
import type { MessageTemplateLogicProps } from './messageTemplateLogic'

export interface GitHubBrandDetectionProps {
    logicProps: MessageTemplateLogicProps
    busyReason?: string
}

export function GitHubBrandDetection({ logicProps, busyReason }: GitHubBrandDetectionProps): JSX.Element {
    const { integrationsLoading } = useValues(integrationsLogic)
    const { location } = useValues(router)
    const integration = resolveTeamGitHubIntegration(useIntegrations('github'))

    if (integration) {
        return (
            <GitHubRepositoryDetection integrationId={integration.id} logicProps={logicProps} busyReason={busyReason} />
        )
    }
    if (integrationsLoading) {
        return <LemonSkeleton className="h-10" />
    }
    return (
        <div className="flex flex-wrap items-center gap-2">
            <span className="text-secondary">Connect GitHub to read your brand from a repository.</span>
            <LemonButton
                data-attr="email-branded-starter-github-connect"
                type="secondary"
                size="small"
                icon={<IconGithub />}
                to={api.integrations.authorizeUrl({
                    kind: 'github',
                    next: location.pathname + location.search,
                })}
                disableClientSideRouting
                disabledReason={busyReason}
            >
                Connect GitHub
            </LemonButton>
        </div>
    )
}
