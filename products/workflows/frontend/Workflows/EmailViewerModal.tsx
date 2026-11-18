import { useState } from 'react'

import { IconLetter } from '@posthog/icons'
import { LemonModal, LemonTabs, Link } from '@posthog/lemon-ui'

import { HogFlow } from './hogflows/types'
import { getMessageAssetContentUrl } from './messageAssetsApi'
import { WorkflowEmailActivity } from './WorkflowEmailActivity'

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
    const [tab, setTab] = useState<'email' | 'activity'>('email')
    return (
        <LemonModal
            isOpen={isOpen}
            onClose={() => {
                setTab('email')
                onClose()
            }}
            width={720}
            title={title}
            description={description}
        >
            <LemonTabs
                activeKey={tab}
                onChange={setTab}
                data-attr="workflow-email-viewer-tabs"
                tabs={[
                    {
                        key: 'email',
                        label: 'Email',
                        content: (
                            <div className="h-[60vh]">
                                {/* The ids clear while the modal closes, and the content URL refuses empty ones. */}
                                {invocationId && actionId && (
                                    <iframe
                                        title="Rendered email"
                                        sandbox=""
                                        src={getMessageAssetContentUrl(workflowId, invocationId, actionId)}
                                        className="w-full h-full bg-white rounded border"
                                    />
                                )}
                            </div>
                        ),
                    },
                    {
                        key: 'activity',
                        label: 'Activity',
                        tooltip: "The person's events in your product in the week before and after this email",
                        content: (
                            <div className="h-[60vh] overflow-y-auto">
                                {invocationId && actionId && (
                                    <WorkflowEmailActivity invocationId={invocationId} actionId={actionId} />
                                )}
                            </div>
                        ),
                    },
                ]}
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
