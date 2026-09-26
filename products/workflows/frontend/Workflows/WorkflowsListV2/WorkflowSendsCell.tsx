import { IconLetter } from '@posthog/icons'
import { Tooltip } from '@posthog/lemon-ui'

import type { FacetFilter } from 'lib/components/FacetSearchBar/facetQuery'

import type { EmailStepSummaryApi } from 'products/workflows/frontend/generated/api.schemas'

import { WorkflowDispatchIcons } from '../WorkflowDispatchIcons'
import { WorkflowListRow } from './workflowListRows'

interface ShownStep {
    step: EmailStepSummaryApi
    /** The From address to show: the one a `from:` pill matched, else the first. */
    address: string | null
    subjectMatched: boolean
    addressMatched: boolean
    moreMatches: number
}

function pickShownStep(steps: readonly EmailStepSummaryApi[], filters: FacetFilter[]): ShownStep | null {
    if (!steps.length) {
        return null
    }
    const sends = filters.filter((f) => !f.negated && f.facet === 'sends').map((f) => f.value.toLowerCase())
    const from = filters.filter((f) => !f.negated && f.facet === 'from').map((f) => f.value.toLowerCase())
    const subjectMatches = (step: EmailStepSummaryApi): boolean => sends.includes(step.subject.toLowerCase())
    const matchedAddress = (step: EmailStepSummaryApi): string | undefined =>
        step.from_addresses.find((address) => from.includes(address.toLowerCase()))
    const matchesAll = (step: EmailStepSummaryApi): boolean =>
        (!sends.length || subjectMatches(step)) && (!from.length || !!matchedAddress(step))
    const matchesAny = (step: EmailStepSummaryApi): boolean => subjectMatches(step) || !!matchedAddress(step)

    if (!sends.length && !from.length) {
        return {
            step: steps[0],
            address: steps[0].from_addresses[0] ?? null,
            subjectMatched: false,
            addressMatched: false,
            moreMatches: 0,
        }
    }
    // Facets match per workflow, so the subject and the sender can sit on different steps.
    const matching = steps.filter(matchesAll).length ? steps.filter(matchesAll) : steps.filter(matchesAny)
    const step = matching[0] ?? steps[0]
    const address = matchedAddress(step)
    return {
        step,
        address: address ?? step.from_addresses[0] ?? null,
        subjectMatched: matching.length > 0 && subjectMatches(step),
        addressMatched: matching.length > 0 && !!address,
        moreMatches: Math.max(0, matching.length - 1),
    }
}

function StepsTooltip({ steps }: { steps: readonly EmailStepSummaryApi[] }): JSX.Element {
    return (
        <div className="flex flex-col gap-1">
            {steps.map((step) => (
                <div key={step.action_id}>
                    <div className="font-semibold">{step.subject || step.name}</div>
                    {step.from_addresses.length > 0 && (
                        <div>
                            From {step.from_name ? `${step.from_name} ` : ''}
                            {step.from_addresses.join(', ')}
                        </div>
                    )}
                </div>
            ))}
        </div>
    )
}

function SendsLine({
    subject,
    address,
    subjectMatched = false,
    addressMatched = false,
}: {
    subject: string
    address: string | null
    subjectMatched?: boolean
    addressMatched?: boolean
}): JSX.Element {
    return (
        <>
            <span data-attr="workflow-sends-subject" className="min-w-0 truncate">
                {subjectMatched ? <mark>{subject}</mark> : subject}
            </span>
            {address && (
                <span className="min-w-0 shrink-[3] truncate text-secondary">
                    · {addressMatched ? <mark>{address}</mark> : address}
                </span>
            )}
        </>
    )
}

/** What a row sends: dispatch icons, then one email subject and its From address. */
export function WorkflowSendsCell({ row, filters }: { row: WorkflowListRow; filters: FacetFilter[] }): JSX.Element {
    if (row.kind === 'email_template') {
        return (
            <div className="flex items-center gap-2 min-w-0 max-w-120">
                <IconLetter className="shrink-0 text-secondary" />
                <SendsLine subject={row.template.subject} address={row.template.from_addresses[0] ?? null} />
            </div>
        )
    }

    const { workflow } = row
    const shown = pickShownStep(workflow.email_steps, filters)
    const line = (
        <div className="flex items-center gap-2 min-w-0 max-w-120">
            <span className="shrink-0">
                <WorkflowDispatchIcons dispatches={workflow.dispatches} />
            </span>
            {shown && (
                <SendsLine
                    subject={shown.step.subject}
                    address={shown.address}
                    subjectMatched={shown.subjectMatched}
                    addressMatched={shown.addressMatched}
                />
            )}
            {shown && shown.moreMatches > 0 && (
                <span data-attr="workflow-sends-more" className="shrink-0 text-secondary">
                    +{shown.moreMatches}
                </span>
            )}
        </div>
    )
    return workflow.email_steps.length ? (
        <Tooltip title={<StepsTooltip steps={workflow.email_steps} />}>{line}</Tooltip>
    ) : (
        line
    )
}
