import { useActions, useValues } from 'kea'

import { IconDownload } from '@posthog/icons'
import { LemonBanner, LemonButton, LemonTabs, LemonTable } from '@posthog/lemon-ui'

import type { ReceivedEmailDetailApi } from 'products/workflows/frontend/generated/api.schemas'

import { buildReceivedEmailDocument, hasRemoteImages } from './receivedEmailHtml'
import { ReceivedEmailBodyTab, receivedEmailLogic } from './receivedEmailLogic'

function Plain({ value, empty }: { value: string; empty: string }): JSX.Element {
    return value ? (
        <pre className="ph-no-capture m-0 p-4 whitespace-pre-wrap break-words text-sm font-mono">{value}</pre>
    ) : (
        <p className="m-0 p-4 text-secondary">{empty}</p>
    )
}

export function ReceivedEmailBody({ email }: { email: ReceivedEmailDetailApi }): JSX.Element {
    const { bodyTab, remoteImagesLoaded } = useValues(receivedEmailLogic)
    const { setBodyTab, loadRemoteImages } = useActions(receivedEmailLogic)
    const remoteImages = hasRemoteImages(email.html)

    const tabs: { key: ReceivedEmailBodyTab; label: string; content: JSX.Element }[] = [
        {
            key: 'preview',
            label: 'Preview',
            content: email.html ? (
                <div className="flex flex-col">
                    {remoteImages && !remoteImagesLoaded && (
                        <div className="flex flex-wrap items-center justify-between gap-2 px-4 py-2 border-b text-sm">
                            <span className="text-secondary">
                                Remote images are blocked, because loading them tells the sender you opened this email.
                            </span>
                            <LemonButton
                                size="xsmall"
                                type="secondary"
                                onClick={() => loadRemoteImages()}
                                data-attr="received-email-load-images"
                            >
                                Load remote images
                            </LemonButton>
                        </div>
                    )}
                    {/* No sandbox permissions: a stranger wrote this HTML, so it must not run scripts or reach this page. */}
                    <iframe
                        title="Email preview"
                        sandbox="allow-popups allow-popups-to-escape-sandbox"
                        srcDoc={buildReceivedEmailDocument(email.html, { allowRemoteImages: remoteImagesLoaded })}
                        className="ph-no-capture w-full h-[60vh] bg-white block"
                        data-attr="received-email-preview"
                    />
                </div>
            ) : (
                <Plain value={email.text} empty="This email has no body." />
            ),
        },
        {
            key: 'text',
            label: 'Plain text',
            content: <Plain value={email.text} empty="This email has no plain text." />,
        },
        {
            key: 'reply',
            label: 'Reply only',
            content: <Plain value={email.reply_text} empty="This email has no plain text." />,
        },
        { key: 'html', label: 'HTML', content: <Plain value={email.html} empty="This email has no HTML." /> },
        {
            key: 'raw',
            label: 'Raw',
            content: (
                <div className="flex flex-col gap-3 p-4">
                    {email.raw.download_url ? (
                        <div className="flex">
                            <LemonButton
                                type="secondary"
                                size="small"
                                icon={<IconDownload />}
                                to={email.raw.download_url}
                                targetBlank
                                data-attr="received-email-download-raw"
                            >
                                Download raw email
                            </LemonButton>
                        </div>
                    ) : (
                        <p className="m-0 text-secondary">The raw email wasn't kept.</p>
                    )}
                    <LemonTable
                        size="small"
                        dataSource={email.headers}
                        rowKey={(header, index) => `${header.name}-${index}`}
                        columns={[
                            {
                                title: 'Header',
                                key: 'name',
                                width: 0,
                                render: (_, header) => (
                                    <span className="font-mono whitespace-nowrap">{header.name}</span>
                                ),
                            },
                            {
                                title: 'Value',
                                key: 'value',
                                render: (_, header) => (
                                    <span className="ph-no-capture font-mono break-all">{header.value}</span>
                                ),
                            },
                        ]}
                        emptyState="No headers kept"
                    />
                </div>
            ),
        },
    ]

    return (
        <section className="border rounded bg-surface-primary overflow-hidden">
            {email.body_truncated && (
                <LemonBanner type="info" className="m-2">
                    This email is very long, so the text here is cut off. Download the raw email from the Raw tab to
                    read all of it.
                </LemonBanner>
            )}
            <LemonTabs activeKey={bodyTab} onChange={setBodyTab} tabs={tabs} barClassName="px-4 mb-0" />
        </section>
    )
}
