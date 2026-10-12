import { IconLetter } from '@posthog/icons'

import type { WorkflowIdeaApi } from '../../generated/api.schemas'
import { waitLabel } from './ideaCopy'

function capitalize(text: string): string {
    return text.charAt(0).toUpperCase() + text.slice(1)
}

/** Who enters an idea's workflow, what it sends and when it stops. */
export function WorkflowIdeaFacts({
    evidence,
    emailCount,
}: {
    evidence: WorkflowIdeaApi['evidence']
    emailCount: number
}): JSX.Element {
    const waits = evidence.waits ?? []
    const schedule =
        waits.length === emailCount && waits.length > 0
            ? `, ${waits.map((wait, index) => (index === 0 ? `${waitLabel(wait)} later` : `then ${waitLabel(wait)} after that`)).join(', ')}`
            : ''

    return (
        <dl className="m-0 grid grid-cols-[auto_1fr] gap-x-3 gap-y-1 text-sm">
            <dt className="text-secondary">Starts</dt>
            <dd className="m-0">
                {evidence.audience ? capitalize(evidence.audience) : 'On'}{' '}
                <code className="text-xs text-secondary" translate="no">
                    {evidence.trigger_event}
                </code>
            </dd>
            <dt className="text-secondary">Sends</dt>
            <dd className="m-0 flex flex-wrap items-center gap-1">
                <IconLetter className="text-secondary" />
                {emailCount === 1 ? '1 email' : `${emailCount} emails`}
                {schedule}
            </dd>
            {evidence.goal && (
                <>
                    <dt className="text-secondary">Stops</dt>
                    <dd className="m-0">As soon as they {evidence.goal}</dd>
                </>
            )}
            {evidence.once_per_person_days ? (
                <>
                    <dt className="text-secondary">Limit</dt>
                    <dd className="m-0">Once per person every {evidence.once_per_person_days} days</dd>
                </>
            ) : null}
        </dl>
    )
}
