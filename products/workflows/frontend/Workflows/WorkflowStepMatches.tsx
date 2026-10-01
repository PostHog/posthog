import { Link } from '@posthog/lemon-ui'

import { pluralize } from 'lib/utils/strings'
import { urls } from 'scenes/urls'

import { HogFlow } from './hogflows/types'
import { WorkflowStepMatch } from './workflowSearchMatches'

const MAX_VISIBLE_STEP_MATCHES = 3

export function WorkflowStepMatches({
    workflow,
    matches,
}: {
    workflow: HogFlow
    matches: WorkflowStepMatch[]
}): JSX.Element {
    const hiddenCount = matches.length - MAX_VISIBLE_STEP_MATCHES
    // An archived workflow has to be restored before it can be edited, so its name is not a link either.
    const canOpenStep = workflow.status !== 'archived'
    return (
        <div className="mt-1 max-w-sm text-xs text-secondary">
            {matches.slice(0, MAX_VISIBLE_STEP_MATCHES).map((match) => {
                const label = `${match.field}: ${match.value}`
                return canOpenStep ? (
                    <Link
                        key={match.actionId}
                        to={`${urls.workflow(workflow.id, 'workflow')}?node=${encodeURIComponent(match.actionId)}`}
                        className="block truncate"
                        data-attr="workflow-search-step-match"
                    >
                        {label}
                    </Link>
                ) : (
                    <span key={match.actionId} className="block truncate" data-attr="workflow-search-step-match">
                        {label}
                    </span>
                )
            })}
            {hiddenCount > 0 && <span>{pluralize(hiddenCount, 'more matching step')}</span>}
        </div>
    )
}
