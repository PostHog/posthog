import { useActions, useValues } from 'kea'

import * as greekPng from '@posthog/brand/hoggies/png/greek'
import { LemonSkeleton, LemonTable, Link } from '@posthog/lemon-ui'

import { pngHoggie } from 'lib/brand/hoggies'
import { TZLabel } from 'lib/components/TZLabel'
import { urls } from 'scenes/urls'

import { EMAIL_STATUS_LABEL } from 'products/workflows/frontend/Transactional/log/emailLogStatus'
import { EmailViewerModal } from 'products/workflows/frontend/Workflows/EmailViewerModal'
import { MessageAsset } from 'products/workflows/frontend/Workflows/messageAssetsApi'

import { EmailLookup, isEmailOutcome, personEmailsLogic } from '../logics/personEmailsLogic'

const HedgehogGreek = pngHoggie(greekPng)

interface PersonEmailsTabProps {
    teamId: number
    personId: string
}

function EmailOutcomeCell({ lookup }: { lookup: EmailLookup | undefined }): JSX.Element | null {
    if (lookup === 'looking') {
        return <LemonSkeleton className="h-4 w-20" />
    }
    if (lookup === 'failed') {
        return <span className="text-secondary">Couldn't load</span>
    }
    if (!lookup || !isEmailOutcome(lookup)) {
        return null
    }
    return <>{lookup === 'delivered' ? 'No open recorded' : EMAIL_STATUS_LABEL[lookup]}</>
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
    const { emails, emailsLoading, lookups, outcomeColumnShown, previewed } = useValues(logic)
    const { openEmail, closePreview } = useActions(logic)

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
                    ...(outcomeColumnShown
                        ? [
                              {
                                  title: 'What it led to',
                                  key: 'outcome',
                                  render: (_: unknown, asset: MessageAsset) => (
                                      <EmailOutcomeCell lookup={lookups?.[asset.invocation_id]} />
                                  ),
                              },
                          ]
                        : []),
                ]}
            />
            <EmailViewerModal
                workflowId={previewed?.function_id ?? ''}
                invocationId={previewed?.invocation_id ?? ''}
                actionId={previewed?.action_id ?? ''}
                isOpen={!!previewed}
                onClose={closePreview}
                title={previewed?.subject || 'Email'}
                description={previewed ? `Sent to ${previewed.recipient}` : undefined}
            />
        </>
    )
}
