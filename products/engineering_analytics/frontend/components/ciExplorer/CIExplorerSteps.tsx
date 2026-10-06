import { useActions, useValues } from 'kea'
import type { CSSProperties } from 'react'

import { Link } from '@posthog/lemon-ui'

import { cn } from 'lib/utils/css-classes'
import { humanFriendlyDuration } from 'lib/utils/durations'

import type { WorkflowJobApi } from '../../generated/api.schemas'
import { statusLabel } from '../../lib/ciExplorerDetails'
import { shownSteps, statusOf } from '../../lib/ciExplorerGraph'
import { githubJobUrl } from '../../lib/github'
import { ciExplorerContextLogic } from '../../scenes/ciExplorerContextLogic'
import { ciExplorerLogic } from '../../scenes/ciExplorerLogic'
import { CIExplorerChips } from './CIExplorerChips'

/**
 * The steps of a focused job, each with a bar for its share of the slowest step. A row opens the step on GitHub.
 * While the Context tab is open, resting on a row or moving the keyboard focus to it compares that step.
 */
export function CIExplorerSteps({ job }: { job: WorkflowJobApi }): JSX.Element {
    const { repoOwner, repoName, focusedJobInsights, focusedBadgedSteps } = useValues(ciExplorerLogic)
    const { active: contextActive, stepNumber: contextStep } = useValues(ciExplorerContextLogic)
    const { selectStep, hoverStep } = useActions(ciExplorerContextLogic)
    const steps = shownSteps(job, focusedBadgedSteps)
    const badgesOf = new Map((focusedJobInsights?.steps ?? []).map((step) => [step.number, step.badges]))
    const longest = Math.max(1, ...steps.map((step) => step.duration_seconds ?? 0))
    const onGitHub = job.ci_engine !== 'depot_ci'

    return (
        <ol className="CIExplorer__steps">
            {steps.map((step) => {
                const running = step.conclusion === null && step.status !== 'completed'
                const status = running ? 'running' : statusOf(step.conclusion)
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
                const className = cn(
                    'CIExplorer__step',
                    status === 'failure' && 'CIExplorer__step--failure',
                    contextActive && contextStep === step.number && 'CIExplorer__step--compared'
                )
                const style = { '--w': Math.max(0.004, (step.duration_seconds ?? 0) / longest) } as CSSProperties
                const compare = contextActive
                    ? {
                          onMouseEnter: () => hoverStep(step.number),
                          onMouseLeave: () => hoverStep(null),
                          onFocus: () => selectStep(step.number),
                      }
                    : {}
                return (
                    // eslint-disable-next-line react/forbid-dom-props
                    <li key={step.number} style={style}>
                        {onGitHub ? (
                            <Link
                                className={className}
                                to={githubJobUrl(repoOwner, repoName, job.run_id, job.id, step.number)}
                                target="_blank"
                                title="Open this step on GitHub in a new tab"
                                aria-label={`${step.name}, ${statusLabel(step.conclusion)}`}
                                data-attr="ci-explorer-step"
                                {...compare}
                            >
                                {row}
                            </Link>
                        ) : (
                            <div className={className} {...compare}>
                                {row}
                            </div>
                        )}
                    </li>
                )
            })}
        </ol>
    )
}
