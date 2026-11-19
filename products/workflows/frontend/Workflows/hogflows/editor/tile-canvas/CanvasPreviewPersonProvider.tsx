import { useValues } from 'kea'
import { useContext } from 'react'

import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { emailPreviewPersonLogic } from 'scenes/hog-functions/email-templater/preview/emailPreviewPersonLogic'
import { EmailPreviewScopeContext } from 'scenes/hog-functions/email-templater/preview/EmailPreviewScopeContext'

import { workflowLogic } from '../../../workflowLogic'
import { CanvasPreviewPersonContext } from './CanvasPreviewPersonContext'
import { emailContent } from './stepValues'

function PreviewPersonScope({ children }: { children: React.ReactNode }): JSX.Element {
    const scope = useContext(EmailPreviewScopeContext)
    const { previewPerson } = useValues(emailPreviewPersonLogic({ scope }))
    return <CanvasPreviewPersonContext.Provider value={previewPerson}>{children}</CanvasPreviewPersonContext.Provider>
}

/** Renders the canvas's email steps as the workflow's preview person, while person previews are on. */
export function CanvasPreviewPersonProvider({ children }: { children: React.ReactNode }): JSX.Element {
    const enabled = useFeatureFlag('WORKFLOWS_EMAIL_PERSON_PREVIEW')
    const { workflow } = useValues(workflowLogic)
    // Looking up people costs a query, so a workflow with no email to preview skips it.
    const hasEmail = workflow.actions.some((action) => !!emailContent(action))
    return enabled && hasEmail ? <PreviewPersonScope>{children}</PreviewPersonScope> : <>{children}</>
}
