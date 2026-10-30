import { useAsyncActions, useValues } from 'kea'
import posthog from 'posthog-js'
import { useEffect, useState } from 'react'

import { LemonBanner } from '@posthog/lemon-ui'

import { fullNameOrEmail } from 'lib/utils/strings'

import { workflowLogic } from './workflowLogic'

export function WorkflowViewOnlyBanner({ id }: { id: string }): JSX.Element | null {
    const { originalWorkflow, isViewOnly } = useValues(workflowLogic)
    const { duplicate } = useAsyncActions(workflowLogic)
    const [duplicating, setDuplicating] = useState(false)
    const owner = originalWorkflow?.created_by

    useEffect(() => {
        if (isViewOnly) {
            posthog.capture('workflow view only banner shown', { workflow_id: id })
        }
    }, [isViewOnly, id])

    if (!isViewOnly) {
        return null
    }

    return (
        <div className="shrink-0" data-attr="workflow-view-only-banner">
            <LemonBanner
                type="info"
                action={{
                    children: 'Duplicate',
                    'data-attr': 'workflow-view-only-duplicate',
                    loading: duplicating,
                    onClick: async () => {
                        posthog.capture('workflow view only duplicated', { workflow_id: id })
                        setDuplicating(true)
                        try {
                            await duplicate()
                        } finally {
                            setDuplicating(false)
                        }
                    },
                }}
            >
                You can view this workflow but not edit it. Ask {owner ? fullNameOrEmail(owner) : 'its owner'} or an
                admin for edit access, or duplicate it to make your own copy.
            </LemonBanner>
        </div>
    )
}
