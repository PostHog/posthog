import { useRef } from 'react'

import {
    Button,
    Dialog,
    DialogBody,
    DialogContent,
    DialogDescription,
    DialogHeader,
    DialogTitle,
    Heading,
    Text,
} from '@posthog/quill'

import { LinkPrimitive } from 'lib/lemon-ui/Link'
import { urls } from 'scenes/urls'

import { MarketingAnalyticsSearchQuery } from '~/queries/schema/schema-general'

import { QuillSearchNotice } from './QuillSearchNotice'
import { SearchSourceNotice } from './searchPerformanceLogic'
import { SearchPerformanceTable } from './SearchPerformanceTable'

export function QuillSearchPerformanceDetail({
    isOpen,
    onClose,
    title,
    description,
    metrics,
    tableHeading,
    tableDescription,
    sourceNotices,
    detailQuery,
    wrapText,
    hasSearchConsole,
    connectSearchConsoleUrl,
}: {
    isOpen: boolean
    onClose: () => void
    title: string
    description: string | undefined
    metrics: { key: string; label: string; value: JSX.Element }[]
    tableHeading: string
    tableDescription: string
    sourceNotices: SearchSourceNotice[]
    detailQuery: MarketingAnalyticsSearchQuery | null
    wrapText: boolean
    hasSearchConsole: boolean
    connectSearchConsoleUrl: string
}): JSX.Element {
    const popupRef = useRef<HTMLDivElement>(null)
    return (
        <Dialog open={isOpen} onOpenChange={(open) => !open && onClose()}>
            {/* Focus starts on the popup: the first tabbable is a metric whose tooltip would open over its label. */}
            <DialogContent ref={popupRef} initialFocus={popupRef} size="wide">
                <DialogHeader>
                    <DialogTitle className="break-all">{title}</DialogTitle>
                    {description ? <DialogDescription>{description}</DialogDescription> : null}
                </DialogHeader>
                <DialogBody>
                    {isOpen && (
                        <div className="@container flex flex-col gap-4">
                            <dl className="m-0 grid grid-cols-2 gap-4 @2xl:grid-cols-4">
                                {metrics.map(({ key, label, value }) => (
                                    <div key={key} className="flex flex-col gap-1">
                                        <Text size="xs" variant="muted" render={<dt className="m-0" />}>
                                            {label}
                                        </Text>
                                        <dd className="m-0 text-lg font-semibold">{value}</dd>
                                    </div>
                                ))}
                            </dl>
                            <div className="flex flex-col gap-1">
                                <Heading size="sm" render={<h3 className="m-0" />}>
                                    {tableHeading}
                                </Heading>
                                <Text size="xs" variant="muted" render={<p className="m-0" />}>
                                    {tableDescription}
                                </Text>
                            </div>
                            {sourceNotices.map(({ sourceId, name, message }) => (
                                <QuillSearchNotice
                                    key={sourceId}
                                    action={
                                        <Button
                                            variant="outline"
                                            nativeButton={false}
                                            render={
                                                <LinkPrimitive to={urls.dataWarehouseSource(`managed-${sourceId}`)} />
                                            }
                                        >
                                            Manage source
                                        </Button>
                                    }
                                >
                                    {`${name}: ${message}`}
                                </QuillSearchNotice>
                            ))}
                            {detailQuery?.sources.length ? (
                                <SearchPerformanceTable
                                    query={detailQuery}
                                    metrics="traffic"
                                    wrapText={wrapText}
                                    queryKey="marketing-search-detail"
                                />
                            ) : !hasSearchConsole ? (
                                <QuillSearchNotice>
                                    Connect Google Search Console to see organic queries and landing pages.
                                </QuillSearchNotice>
                            ) : null}
                            {!hasSearchConsole && (
                                <Button
                                    variant="primary"
                                    className="self-start"
                                    nativeButton={false}
                                    render={<LinkPrimitive to={connectSearchConsoleUrl} />}
                                >
                                    Connect Google Search Console
                                </Button>
                            )}
                            <Text size="xs" variant="muted" render={<p className="m-0" />}>
                                Google can withhold low-volume queries. Query and page breakdowns may not add up to
                                property totals.
                            </Text>
                        </div>
                    )}
                </DialogBody>
            </DialogContent>
        </Dialog>
    )
}
