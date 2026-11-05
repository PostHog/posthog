import posthog from 'posthog-js'

import { IconGithub, IconNotebook } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { humanFriendlyCurrency } from 'lib/utils/numbers'
import { urls } from 'scenes/urls'

import type { WizardRunApi, WizardRunArtifactApi, WizardSpendProjectionItemApi } from '../../generated/api.schemas'
import { WizardSpendAuditCreatedList } from './WizardSpendAuditCreatedList'
import { type WizardSpendAuditAccountOwner, WizardSpendAuditOwnerContact } from './WizardSpendAuditOwnerContact'
import type { WizardRunNotebookArtifact } from './wizardSpendAuditResultsLogic'

type WizardRunSpendProjectionArtifact = Extract<WizardRunArtifactApi, { artifact_type: 'spend_projection' }>
type WizardRunPullRequestArtifact = Extract<WizardRunArtifactApi, { artifact_type: 'pull_request' }>

// The modal shows the largest few; the notebook lists every recommendation.
const VISIBLE_RECOMMENDATIONS = 3

// Savings are estimates, so cents would claim a precision the audit does not have.
function formatDollars(amount: number): string {
    return humanFriendlyCurrency(Math.round(amount), 0)
}

function formatRange(low: number, high: number): string {
    const lowText = formatDollars(low)
    const highText = formatDollars(high)
    return lowText === highText ? lowText : `${lowText} to ${highText}`
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
                    {formatDollars(baseline)}
                </p>
            )}
        </>
    )
}

function Recommendation({ item }: { item: WizardSpendProjectionItemApi }): JSX.Element {
    return (
        <li className="flex items-start gap-4">
            <div className="min-w-0 flex-1">
                <div className="text-sm ph-no-capture">{item.title}</div>
                <div className="text-xs text-muted">
                    {item.fixed_in === 'pr' ? 'In the pull request' : 'In settings'}
                </div>
            </div>
            <span className="shrink-0 text-sm tabular-nums">
                {formatRange(item.saving_monthly.low, item.saving_monthly.high)}/mo
            </span>
        </li>
    )
}

export function WizardSpendAuditResults({
    run,
    artifacts,
    accountOwner = null,
    organizationName = null,
}: {
    run: WizardRunApi
    artifacts: readonly WizardRunArtifactApi[]
    accountOwner?: WizardSpendAuditAccountOwner | null
    organizationName?: string | null
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
        <div className="mt-3 flex flex-col gap-4" data-attr="wizard-spend-audit-results">
            <div className="flex flex-col gap-1">
                <Headline projection={projection} />
            </div>

            {recommendations.length > 0 && (
                <ul className="m-0 list-none space-y-2 p-0">
                    {recommendations.map((item) => (
                        <Recommendation key={item.id} item={item} />
                    ))}
                </ul>
            )}

            <div className="flex flex-wrap items-center gap-2">
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
                {pullRequest ? (
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
                ) : (
                    <span className="text-xs text-muted">No code changes needed.</span>
                )}
            </div>

            {accountOwner && (
                <WizardSpendAuditOwnerContact
                    owner={accountOwner}
                    placement="after_run"
                    organizationName={organizationName}
                    savingText={
                        projection && projection.saving_monthly.high > 0
                            ? formatRange(projection.saving_monthly.low, projection.saving_monthly.high)
                            : null
                    }
                />
            )}

            {notebook && (
                <WizardSpendAuditCreatedList projectId={String(run.team_id)} runId={run.id} notebook={notebook} />
            )}
        </div>
    )
}
