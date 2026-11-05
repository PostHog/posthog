import posthog from 'posthog-js'

import { IconGithub, IconNotebook } from '@posthog/icons'
import { LemonButton, LemonTag } from '@posthog/lemon-ui'

import { humanFriendlyCurrency } from 'lib/utils/numbers'
import { urls } from 'scenes/urls'

import type { WizardRunApi, WizardRunArtifactApi } from '../../generated/api.schemas'
import { WizardSpendAuditCreatedList } from './WizardSpendAuditCreatedList'
import type { WizardRunNotebookArtifact } from './wizardSpendAuditResultsLogic'

type WizardRunSpendProjectionArtifact = Extract<WizardRunArtifactApi, { artifact_type: 'spend_projection' }>
type WizardRunPullRequestArtifact = Extract<WizardRunArtifactApi, { artifact_type: 'pull_request' }>

// The modal shows the largest few; the notebook lists every recommendation.
const VISIBLE_RECOMMENDATIONS = 3

function formatRange(low: number, high: number): string {
    const lowText = humanFriendlyCurrency(Math.round(low))
    return Math.round(low) === Math.round(high) ? lowText : `${lowText} to ${humanFriendlyCurrency(Math.round(high))}`
}

function Headline({ projection }: { projection: WizardRunSpendProjectionArtifact | null }): JSX.Element {
    if (!projection) {
        return (
            <>
                <div className="text-base font-semibold">Audit complete</div>
                <p className="m-0 text-xs text-muted">We couldn't estimate savings for this run.</p>
            </>
        )
    }
    if (projection.saving_monthly.high <= 0) {
        return (
            <>
                <div className="text-base font-semibold">Your setup is already lean</div>
                <p className="m-0 text-xs text-muted">The audit found nothing to cut from your bill.</p>
            </>
        )
    }
    const baseline = projection.baseline_monthly
    return (
        <>
            <div className="text-base font-semibold">
                Save about {formatRange(projection.saving_monthly.low, projection.saving_monthly.high)} a month
            </div>
            {baseline > 0 && (
                <p className="m-0 text-xs text-muted">
                    About {Math.round((projection.saving_monthly.low / baseline) * 100)} to{' '}
                    {Math.round((projection.saving_monthly.high / baseline) * 100)}% of your projected bill of{' '}
                    {humanFriendlyCurrency(Math.round(baseline))}
                </p>
            )}
        </>
    )
}

export function WizardSpendAuditResults({
    run,
    artifacts,
}: {
    run: WizardRunApi
    artifacts: readonly WizardRunArtifactApi[]
}): JSX.Element {
    const notebook = artifacts.find(
        (artifact): artifact is WizardRunNotebookArtifact => artifact.artifact_type === 'notebook'
    )
    const projection =
        artifacts.find(
            (artifact): artifact is WizardRunSpendProjectionArtifact => artifact.artifact_type === 'spend_projection'
        ) ?? null
    const pullRequest = artifacts.find(
        (artifact): artifact is WizardRunPullRequestArtifact => artifact.artifact_type === 'pull_request'
    )
    const recommendations = (projection?.items ?? []).slice(0, VISIBLE_RECOMMENDATIONS)

    return (
        <div className="mt-3 flex flex-col gap-3" data-attr="wizard-spend-audit-results">
            <div className="flex flex-col gap-1">
                <Headline projection={projection} />
            </div>

            {recommendations.length > 0 && (
                <ul className="m-0 list-none space-y-1 p-0">
                    {recommendations.map((item) => (
                        <li key={item.id} className="flex min-w-0 items-center gap-2 text-xs">
                            <LemonTag size="small">{item.fixed_in === 'pr' ? 'Pull request' : 'Settings'}</LemonTag>
                            <span className="min-w-0 flex-1 truncate ph-no-capture">{item.title}</span>
                            <span className="shrink-0 tabular-nums text-muted">
                                {formatRange(item.saving_monthly.low, item.saving_monthly.high)}/mo
                            </span>
                        </li>
                    ))}
                </ul>
            )}

            {!pullRequest && <p className="m-0 text-xs text-muted">No code changes needed.</p>}

            <div className="flex flex-wrap gap-2">
                {notebook && (
                    <LemonButton
                        type="primary"
                        size="small"
                        icon={<IconNotebook />}
                        to={urls.notebook(notebook.short_id)}
                        onClick={() => posthog.capture('spend audit notebook opened', { wizard_run_id: run.id })}
                        data-attr="wizard-spend-audit-open-notebook"
                    >
                        Open notebook
                    </LemonButton>
                )}
                {pullRequest && (
                    <LemonButton
                        type={notebook ? 'secondary' : 'primary'}
                        size="small"
                        icon={<IconGithub />}
                        to={pullRequest.url}
                        targetBlank
                        onClick={() => posthog.capture('spend audit pr opened', { wizard_run_id: run.id })}
                        data-attr="wizard-spend-audit-review-pr"
                    >
                        Review pull request
                    </LemonButton>
                )}
            </div>

            {notebook && (
                <WizardSpendAuditCreatedList projectId={String(run.team_id)} runId={run.id} notebook={notebook} />
            )}
        </div>
    )
}
