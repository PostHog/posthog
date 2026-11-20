import { useEffect, useState } from 'react'

import { IconLetter, IconPulse } from '@posthog/icons'
import { LemonButton, LemonModal, LemonTabs, Link } from '@posthog/lemon-ui'

import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'

import { HogFlow } from './hogflows/types'
import { getMessageAssetContentUrl } from './messageAssetsApi'
import { WorkflowEmailActivity } from './WorkflowEmailActivity'

type EmailViewerTab = 'email' | 'activity'

interface EmailViewerModalProps {
    workflowId: HogFlow['id']
    invocationId: string
    actionId: string
    isOpen: boolean
    onClose: () => void
    title?: string
    description?: string
    initialTab?: EmailViewerTab
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
    initialTab = 'email',
}: EmailViewerModalProps): JSX.Element {
    const activityEnabled = useFeatureFlag('WORKFLOWS_EMAIL_ACTIVITY')
    const [tab, setTab] = useState<EmailViewerTab>(initialTab)
    // Kept mounted once opened, so switching back doesn't reload the activity.
    const [activityOpened, setActivityOpened] = useState(initialTab === 'activity')
    useEffect(() => {
        if (isOpen) {
            setTab(initialTab)
            setActivityOpened(initialTab === 'activity')
        }
    }, [isOpen, initialTab])
    const emailContent = (
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
    )
    return (
        <LemonModal
            isOpen={isOpen}
            onClose={() => {
                setTab('email')
                setActivityOpened(false)
                onClose()
            }}
            width={720}
            title={title}
            description={description}
        >
            {activityEnabled ? (
                <LemonTabs
                    activeKey={tab}
                    onChange={(key) => {
                        setTab(key)
                        if (key === 'activity') {
                            setActivityOpened(true)
                        }
                    }}
                    data-attr="workflow-email-viewer-tabs"
                    tabs={[
                        {
                            key: 'email',
                            label: 'Email',
                            keepMounted: true,
                            content: emailContent,
                        },
                        {
                            key: 'activity',
                            label: 'Activity',
                            tooltip: "The person's events in your product in the week before and after this email",
                            keepMounted: activityOpened,
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
            ) : (
                emailContent
            )}
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
    const activityEnabled = useFeatureFlag('WORKFLOWS_EMAIL_ACTIVITY')
    const [openTab, setOpenTab] = useState<EmailViewerTab | null>(null)
    return (
        <>
            {activityEnabled ? (
                <span className="inline-flex items-center gap-1 whitespace-nowrap align-middle">
                    <LemonButton
                        size="xsmall"
                        type="secondary"
                        icon={<IconLetter />}
                        tooltip="View the email that was sent"
                        data-attr="workflow-log-view-email"
                        onClick={(e) => {
                            e.stopPropagation()
                            setOpenTab('email')
                        }}
                    >
                        Email
                    </LemonButton>
                    <LemonButton
                        size="xsmall"
                        type="secondary"
                        icon={<IconPulse />}
                        tooltip="See what the person did before and after this email"
                        data-attr="workflow-log-view-email-activity"
                        onClick={(e) => {
                            e.stopPropagation()
                            setOpenTab('activity')
                        }}
                    >
                        Activity
                    </LemonButton>
                </span>
            ) : (
                <Link
                    className="rounded p-1 -m-1 bg-border text-bg-primary"
                    onClick={(e) => {
                        e.stopPropagation()
                        setOpenTab('email')
                    }}
                >
                    <span className="mr-1">
                        <IconLetter />
                    </span>
                    View email
                </Link>
            )}
            <EmailViewerModal
                workflowId={workflowId}
                invocationId={invocationId}
                actionId={actionId}
                isOpen={openTab !== null}
                initialTab={openTab ?? 'email'}
                onClose={() => setOpenTab(null)}
            />
        </>
    )
}
