import { Panel } from '@xyflow/react'
import { useValues } from 'kea'

import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { EmailPreviewPersonBar } from 'scenes/hog-functions/email-templater/preview/EmailPreviewPersonBar'

import { workflowLogic } from '../../../workflowLogic'
import { emailContent } from './stepValues'

/** Says whose values the canvas's email steps show, and lets the viewer swap who that is. */
export function CanvasPreviewPersonPanel(): JSX.Element | null {
    const enabled = useFeatureFlag('WORKFLOWS_EMAIL_PERSON_PREVIEW')
    const { workflow } = useValues(workflowLogic)
    const templates = workflow.actions.flatMap((action) => {
        const email = emailContent(action)
        return email ? [email.subject, email.html ?? '', email.text ?? ''] : []
    })

    if (!enabled || templates.length === 0) {
        return null
    }
    return (
        <Panel position="top-right" className="!m-2 overflow-hidden rounded border @max-[56rem]/tile-canvas:hidden">
            <EmailPreviewPersonBar templates={templates} unresolvedCount={0} />
        </Panel>
    )
}
