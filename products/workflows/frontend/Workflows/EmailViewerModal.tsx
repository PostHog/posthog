import { useState } from 'react'

import { IconLetter } from '@posthog/icons'
import { LemonModal, Link } from '@posthog/lemon-ui'

import { HogFlow } from './hogflows/types'
import { getMessageAssetContentUrl } from './messageAssetsApi'

interface EmailViewerModalProps {
    workflowId: HogFlow['id']
    invocationId: string
    actionId: string
    isOpen: boolean
    onClose: () => void
    title?: string
    description?: string
}

// sandbox="" disables scripts so the captured email HTML can't run anything.
export function EmailViewerModal({
    workflowId,
    invocationId,
    actionId,
    isOpen,
    onClose,
    title = 'Email',
    description,
}: EmailViewerModalProps): JSX.Element {
    return (
        <LemonModal isOpen={isOpen} onClose={onClose} width={720} title={title} description={description}>
            <iframe
                title="Rendered email"
                sandbox=""
                src={getMessageAssetContentUrl(workflowId, invocationId, actionId)}
                className="w-full h-[60vh] bg-white rounded border"
            />
        </LemonModal>
    )
}

// Inline chip used by `renderWorkflowLogMessage` when the email service emits the
// `[Email:<invocation_id>:<action_id>]` token alongside its success log line.
export function EmailViewerChip({
    workflowId,
    invocationId,
    actionId,
}: {
    workflowId: HogFlow['id']
    invocationId: string
    actionId: string
}): JSX.Element {
    const [open, setOpen] = useState(false)
    return (
        <>
            <Link
                className="rounded p-1 -m-1 bg-border text-bg-primary"
                onClick={(e) => {
                    e.stopPropagation()
                    setOpen(true)
                }}
            >
                <span className="mr-1">
                    <IconLetter />
                </span>
                View email
            </Link>
            <EmailViewerModal
                workflowId={workflowId}
                invocationId={invocationId}
                actionId={actionId}
                isOpen={open}
                onClose={() => setOpen(false)}
            />
        </>
    )
}
