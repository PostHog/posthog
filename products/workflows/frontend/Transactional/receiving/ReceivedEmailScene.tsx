import { useActions, useValues } from 'kea'

import { IconDownload, IconDocument } from '@posthog/icons'
import { LemonBanner, LemonButton, LemonSkeleton } from '@posthog/lemon-ui'

import { NotFound } from 'lib/components/NotFound'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { SceneExport } from 'scenes/sceneTypes'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'
import { ProductKey } from '~/queries/schema/schema-general'

import { ReceivedEmailBody } from './ReceivedEmailBody'
import { ReceivedEmailDetails } from './ReceivedEmailDetails'
import { FILTER_REASON_DESCRIPTION, formatBytes } from './receivedEmailLabels'
import { ReceivedEmailLogicProps, receivedEmailLogic } from './receivedEmailLogic'

export const scene: SceneExport<ReceivedEmailLogicProps> = {
    component: ReceivedEmailScene,
    logic: receivedEmailLogic,
    paramsToProps: ({ params: { id } }): ReceivedEmailLogicProps => ({ id }),
    productKey: ProductKey.WORKFLOWS,
}

export function ReceivedEmailScene(): JSX.Element {
    const enabled = useFeatureFlag('WORKFLOWS_INBOUND_EMAIL')
    const { email, emailLoading, emailFailed } = useValues(receivedEmailLogic)
    const { loadEmail } = useActions(receivedEmailLogic)

    if (!enabled) {
        return <NotFound object="page" />
    }
    if (emailFailed && !emailLoading) {
        return (
            <SceneContent>
                <LemonBanner
                    type="error"
                    action={{ children: 'Try again', onClick: () => loadEmail(), 'data-attr': 'received-email-retry' }}
                >
                    This email couldn't load. Check your connection and try again.
                </LemonBanner>
            </SceneContent>
        )
    }
    if (email === null && !emailLoading) {
        return <NotFound object="email" caption="This project has no email with this ID, or it's older than 30 days." />
    }

    // An inline image the email couldn't embed still has its cid: reference, so it stays reachable here.
    const visibleAttachments =
        email?.attachments.filter(
            (attachment) =>
                !attachment.inline || !attachment.content_id || email.html.includes(`cid:${attachment.content_id}`)
        ) ?? []

    return (
        <SceneContent>
            <div className="ph-no-capture contents">
                <SceneTitleSection
                    name={email ? email.subject || '(no subject)' : 'Email'}
                    description={null}
                    resourceType={{ type: 'transactional' }}
                    isLoading={!email}
                />
            </div>
            {!email ? (
                <LemonSkeleton className="h-96" />
            ) : (
                <div className="flex flex-col gap-3">
                    {!email.sender_verified && (
                        <LemonBanner type="warning" className="ph-no-capture" data-attr="received-email-unverified">
                            We couldn't prove this email came from {email.from_address || 'the address it shows'}.
                            Anyone can write any address as the sender, so don't trust it until you've checked.
                        </LemonBanner>
                    )}
                    {email.status === 'filtered' && (
                        <LemonBanner type="info">{FILTER_REASON_DESCRIPTION[email.filter_reason]}</LemonBanner>
                    )}
                    {email.content_status === 'too_large' && (
                        <LemonBanner type="info">
                            This email was over the 40 MB limit, so only its details were kept.
                        </LemonBanner>
                    )}
                    {email.content_status === 'parse_failed' && (
                        <LemonBanner type="info">
                            We couldn't read this email, but the raw message is kept.{' '}
                            {email.verdicts.virus === 'pass' ? 'Download it from the Raw tab.' : null}
                        </LemonBanner>
                    )}
                    {email.content_status === 'not_stored' && (
                        <LemonBanner type="info">This email was filtered, so only its details were kept.</LemonBanner>
                    )}
                    {email.verdicts.virus !== 'pass' && email.content_status !== 'not_stored' && (
                        <LemonBanner type="warning" data-attr="received-email-scan-not-passed">
                            The virus scan didn't pass for this email, so its files can't be downloaded.
                        </LemonBanner>
                    )}
                    <div className="grid gap-3 grid-cols-1 @3xl/main-content:grid-cols-[minmax(0,1fr)_18rem] min-[1200px]:grid-cols-[minmax(0,1fr)_18rem] items-start">
                        <div className="flex flex-col gap-3 min-w-0">
                            <section className="border rounded bg-surface-primary overflow-hidden">
                                <dl className="ph-no-capture m-0 px-4 py-3 grid grid-cols-[auto_1fr] gap-x-4 gap-y-1 text-sm">
                                    <dt className="text-secondary">From</dt>
                                    <dd className="m-0 break-words" data-attr="received-email-from">
                                        {email.from_name
                                            ? `${email.from_name} <${email.from_address}>`
                                            : email.from_address}
                                    </dd>
                                    <dt className="text-secondary">To</dt>
                                    <dd className="m-0 break-words">{email.to.join(', ') || '(not shown)'}</dd>
                                    {email.cc.length > 0 && (
                                        <>
                                            <dt className="text-secondary">Cc</dt>
                                            <dd className="m-0 break-words">{email.cc.join(', ')}</dd>
                                        </>
                                    )}
                                    {email.reply_to.length > 0 && (
                                        <>
                                            <dt className="text-secondary">Reply-To</dt>
                                            <dd className="m-0 break-words">{email.reply_to.join(', ')}</dd>
                                        </>
                                    )}
                                    <dt className="text-secondary">Received at</dt>
                                    <dd className="m-0 break-words">{email.envelope_recipients.join(', ')}</dd>
                                </dl>
                            </section>
                            {email.content_status === 'available' || email.content_status === 'parse_failed' ? (
                                <ReceivedEmailBody email={email} />
                            ) : null}
                            {visibleAttachments.length > 0 && (
                                <section className="border rounded bg-surface-primary p-4 flex flex-col gap-2">
                                    <h3 className="text-sm font-semibold m-0">
                                        Attachments ({visibleAttachments.length})
                                    </h3>
                                    {visibleAttachments.map((attachment) => (
                                        <div
                                            key={attachment.id}
                                            className="flex items-center justify-between gap-2 text-sm"
                                        >
                                            <span className="ph-no-capture flex items-center gap-1.5 min-w-0">
                                                <IconDocument className="text-secondary shrink-0" />
                                                <span className="truncate">{attachment.filename}</span>
                                                <span className="text-secondary shrink-0">
                                                    {formatBytes(attachment.size)}
                                                </span>
                                            </span>
                                            {attachment.download_url ? (
                                                <LemonButton
                                                    size="xsmall"
                                                    type="secondary"
                                                    icon={<IconDownload />}
                                                    to={attachment.download_url}
                                                    targetBlank
                                                    className="ph-no-capture"
                                                    data-attr="received-email-download-attachment"
                                                >
                                                    Download
                                                </LemonButton>
                                            ) : (
                                                <span className="text-secondary shrink-0">Not available</span>
                                            )}
                                        </div>
                                    ))}
                                    {email.attachments_dropped > 0 && (
                                        <p className="m-0 text-xs text-secondary">
                                            {email.attachments_dropped} more weren't kept, because the email had too
                                            many.
                                        </p>
                                    )}
                                </section>
                            )}
                        </div>
                        <ReceivedEmailDetails email={email} />
                    </div>
                </div>
            )}
        </SceneContent>
    )
}
