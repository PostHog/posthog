import { useValues } from 'kea'
import { router } from 'kea-router'
import { useState } from 'react'

import * as greekPng from '@posthog/brand/hoggies/png/greek'
import { LemonTable, Link } from '@posthog/lemon-ui'

import { pngHoggie } from 'lib/brand/hoggies'
import { TZLabel } from 'lib/components/TZLabel'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { urls } from 'scenes/urls'

import { transactionalSendPageUrl } from 'products/workflows/frontend/Transactional/transactionalEmailUrl'
import { EmailViewerModal } from 'products/workflows/frontend/Workflows/EmailViewerModal'
import { MessageAsset } from 'products/workflows/frontend/Workflows/messageAssetsApi'

import { personEmailsLogic } from '../logics/personEmailsLogic'

const HedgehogGreek = pngHoggie(greekPng)

interface PersonEmailsTabProps {
    teamId: number
    personId: string
}

function EmptyEmails(): JSX.Element {
    return (
        <div className="flex flex-col bg-surface-primary rounded px-4 py-8 items-center text-center mx-auto">
            <HedgehogGreek width="100" height="100" className="mb-4" />
            <h2 className="text-xl leading-tight">No emails sent to this person</h2>
            <p className="text-sm text-balance text-tertiary">
                Once a workflow sends this person an email, it will show up here.
            </p>
        </div>
    )
}

export function PersonEmailsTab({ teamId, personId }: PersonEmailsTabProps): JSX.Element {
    const logic = personEmailsLogic({ teamId, personId })
    const { emails, emailsLoading } = useValues(logic)
    const [selected, setSelected] = useState<MessageAsset | null>(null)
    const sendTimeline = useFeatureFlag('WORKFLOWS_EMAIL_SEND_TIMELINE')
    const transactionalLog = useFeatureFlag('WORKFLOWS_TRANSACTIONAL_EMAIL_API')

    const openEmail = (asset: MessageAsset): void => {
        const sendPageUrl = sendTimeline && transactionalLog ? transactionalSendPageUrl(asset) : null
        if (sendPageUrl) {
            router.actions.push(sendPageUrl)
        } else {
            setSelected(asset)
        }
    }

    return (
        <>
            <LemonTable
                loading={emailsLoading}
                dataSource={emails}
                onRow={(asset: MessageAsset) => ({
                    onClick: () => openEmail(asset),
                    className: 'cursor-pointer',
                })}
                emptyState={<EmptyEmails />}
                columns={[
                    {
                        title: 'Subject',
                        dataIndex: 'subject',
                        key: 'subject',
                    },
                    {
                        title: 'Workflow',
                        key: 'function_id',
                        render: (_, asset: MessageAsset) => (
                            <Link
                                to={`${urls.workflow(asset.function_id, 'workflow')}?assetInvocation=${encodeURIComponent(
                                    asset.invocation_id
                                )}`}
                                onClick={(e) => e.stopPropagation()}
                            >
                                {asset.function_name || asset.function_id}
                            </Link>
                        ),
                    },
                    {
                        title: 'Sent',
                        key: 'sent_at',
                        render: (_, asset: MessageAsset) => <TZLabel time={asset.sent_at} />,
                    },
                ]}
            />
            <EmailViewerModal
                workflowId={selected?.function_id ?? ''}
                invocationId={selected?.invocation_id ?? ''}
                actionId={selected?.action_id ?? ''}
                isOpen={!!selected}
                onClose={() => setSelected(null)}
                title={selected?.subject || 'Email'}
                description={selected ? `Sent to ${selected.recipient}` : undefined}
            />
        </>
    )
}
