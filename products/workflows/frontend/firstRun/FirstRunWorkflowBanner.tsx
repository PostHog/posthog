import { useActions, useMountedLogic, useValues } from 'kea'

import { LemonBanner } from '@posthog/lemon-ui'

import { PropertyKeyInfo } from 'lib/components/PropertyKeyInfo'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { pluralize } from 'lib/utils/strings'

import { isEmailAction } from '../Workflows/hogflows/steps/types'
import type { HogFlow } from '../Workflows/hogflows/types'
import { workflowLogic } from '../Workflows/workflowLogic'
import { EnableEngagementEventsAction } from './EnableEngagementEventsAction'
import { firstRunWorkflowBannerLogic } from './firstRunWorkflowBannerLogic'

function triggerEventOf(workflow: HogFlow): string | null {
    const trigger = workflow.actions.find((action) => action.type === 'trigger')
    if (trigger?.type !== 'trigger' || trigger.config.type !== 'event') {
        return null
    }
    return trigger.config.filters?.events?.[0]?.id ?? null
}

function WorkflowSummary({ workflow }: { workflow: HogFlow }): JSX.Element {
    const emails = pluralize(workflow.actions.filter(isEmailAction).length, 'email')
    const triggerEvent = triggerEventOf(workflow)

    if (!triggerEvent) {
        return <>Each person it reaches gets up to {emails}.</>
    }
    return (
        <>
            Each person who triggers{' '}
            <PropertyKeyInfo
                value={triggerEvent}
                type={TaxonomicFilterGroupType.Events}
                disablePopover
                className="font-semibold"
            />{' '}
            gets up to {emails}.
        </>
    )
}

export function FirstRunWorkflowBanner(): JSX.Element | null {
    const { props: workflowLogicProps } = useMountedLogic(workflowLogic)
    const logic = firstRunWorkflowBannerLogic(workflowLogicProps)
    const { banner, originalWorkflow } = useValues(logic)
    const { dismiss, viewMetrics } = useActions(logic)

    if (!banner || !originalWorkflow) {
        return null
    }

    if (banner === 'draft') {
        return (
            <LemonBanner type="info" onClose={dismiss} className="shrink-0">
                <div className="flex flex-col gap-1">
                    <strong>This workflow is not sending yet.</strong>
                    <span className="font-normal">
                        <WorkflowSummary workflow={originalWorkflow} /> Enable it to start sending.
                    </span>
                </div>
            </LemonBanner>
        )
    }

    return (
        <LemonBanner
            type="success"
            onClose={dismiss}
            className="shrink-0"
            action={{
                children: 'View metrics',
                onClick: viewMetrics,
                'data-attr': 'workflows-first-run-view-metrics',
            }}
        >
            <div className="flex flex-col gap-1">
                <strong>Your workflow is sending.</strong>
                <span className="font-normal">
                    <WorkflowSummary workflow={originalWorkflow} /> The Metrics tab shows what it has sent.
                </span>
                <EnableEngagementEventsAction />
            </div>
        </LemonBanner>
    )
}
