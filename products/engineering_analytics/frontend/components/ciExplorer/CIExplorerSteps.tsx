import { useValues } from 'kea'
import type { CSSProperties } from 'react'

import { Link } from '@posthog/lemon-ui'

import { cn } from 'lib/utils/css-classes'
import { humanFriendlyDuration } from 'lib/utils/durations'

import type { WorkflowJobApi } from '../../generated/api.schemas'
import { shownSteps, statusOf } from '../../lib/ciExplorerGraph'
import { githubRunUrl } from '../../lib/github'
import { ciExplorerLogic } from '../../scenes/ciExplorerLogic'
import { CIExplorerChips } from './CIExplorerChips'

/** The steps of a focused job, each with a bar for its share of the slowest step. A row opens the step on GitHub. */
export function CIExplorerSteps({ job }: { job: WorkflowJobApi }): JSX.Element {
    const { repoOwner, repoName, focusedJobInsights, focusedBadgedSteps } = useValues(ciExplorerLogic)
    const steps = shownSteps(job, focusedBadgedSteps)
    const badgesOf = new Map((focusedJobInsights?.steps ?? []).map((step) => [step.number, step.badges]))
    const longest = Math.max(1, ...steps.map((step) => step.duration_seconds ?? 0))
    const jobUrl =
        job.ci_engine === 'depot_ci' ? null : `${githubRunUrl(repoOwner, repoName, job.run_id)}/job/${job.id}`

    return (
        <ol className="CIExplorer__steps">
            {steps.map((step) => {
                const status =
                    step.conclusion === null && step.status !== 'completed' ? 'running' : statusOf(step.conclusion)
                const row = (
                    <>
                        <span className="CIExplorer__stepIndex">{step.number}</span>
                        <span className="CIExplorer__stepLabel">
                            <span className="CIExplorer__stepName" title={step.name}>
                                {step.name}
                            </span>
                            <CIExplorerChips badges={badgesOf.get(step.number) ?? []} />
                        </span>
                        <span className="CIExplorer__duration">
                            {step.duration_seconds === null
                                ? ''
                                : humanFriendlyDuration(step.duration_seconds, { maxUnits: 2 })}
                        </span>
                    </>
                )
                const className = cn('CIExplorer__step', status === 'failure' && 'CIExplorer__step--failure')
                const style = { '--w': Math.max(0.004, (step.duration_seconds ?? 0) / longest) } as CSSProperties
                return (
                    // eslint-disable-next-line react/forbid-dom-props
                    <li key={step.number} style={style}>
                        {jobUrl ? (
                            <Link
                                className={className}
                                to={`${jobUrl}#step:${step.number}:1`}
                                target="_blank"
                                title="Open this step on GitHub in a new tab"
                                data-attr="ci-explorer-step"
                            >
                                {row}
                            </Link>
                        ) : (
                            <div className={className}>{row}</div>
                        )}
                    </li>
                )
            })}
        </ol>
    )
}
