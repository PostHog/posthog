import { useActions, useValues } from 'kea'

import { LemonBanner, LemonButton, LemonModal } from '@posthog/lemon-ui'

import { RestrictionScope, useRestrictedArea } from 'lib/components/RestrictedArea'
import { TeamMembershipLevel } from 'lib/constants'
import { GithubIntegration } from 'scenes/integrations/components/GithubIntegration'
import { IntegrationAccessRequest } from 'scenes/integrations/components/IntegrationAccessRequest'
import { urls } from 'scenes/urls'

import { reportGithubAccessLogic } from '../../logics/reportGithubAccessLogic'
import { SignalReport } from '../../types'

export function ReportGithubConnection({
    report,
    surface,
}: {
    report: SignalReport
    surface: 'detail_pane' | 'triage_mode'
}): JSX.Element {
    const logic = reportGithubAccessLogic({ report, surface })
    const { connectionOpen, loading, failed } = useValues(logic)
    const { setConnectionOpen, retryAccess } = useActions(logic)
    const restricted = useRestrictedArea({
        scope: RestrictionScope.Project,
        minimumAccessLevel: TeamMembershipLevel.Member,
    })
    return (
        <LemonModal title="Connect GitHub" isOpen={connectionOpen} onClose={() => setConnectionOpen(false)}>
            <div className="flex max-w-xl flex-col gap-4">
                <p className="m-0">
                    Connect a GitHub account and give PostHog access to {report.repo_slug || 'your repository'} to
                    create a pull request for this report.
                </p>
                {restricted ? (
                    <IntegrationAccessRequest kind="github" name="GitHub" />
                ) : (
                    <GithubIntegration
                        next={urls.inboxReport('reports', report.id)}
                        connectSurface={surface === 'triage_mode' ? 'inbox_triage' : 'inbox_report'}
                        connectText="Connect GitHub account"
                        emphasizeConnect
                        showPersonalConnectionHelp={false}
                        connectDescription=""
                    />
                )}
                {failed && <LemonBanner type="error">Couldn't check GitHub access. Try again.</LemonBanner>}
                <LemonButton
                    type="secondary"
                    onClick={retryAccess}
                    loading={loading}
                    data-attr="inbox-report-recheck-github"
                >
                    Check access again
                </LemonButton>
            </div>
        </LemonModal>
    )
}
