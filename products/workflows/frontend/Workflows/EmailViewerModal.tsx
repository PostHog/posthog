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
                // Withholding `allow-scripts` and `allow-same-origin` keeps the captured email
                // HTML from running anything. `allow-popups` lets a link click open a new tab,
                // and `allow-popups-to-escape-sandbox` drops the restrictions on that tab so the
                // destination renders as a normal page. The response carries
                // `<base target="_blank">`, so the click goes to that tab instead of navigating
                // this frame into a site that refuses to be framed.
                sandbox="allow-popups allow-popups-to-escape-sandbox"
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
