import {
    Button,
    Dialog,
    DialogBody,
    DialogContent,
    DialogFooter,
    DialogHeader,
    DialogTitle,
    Item,
    ItemContent,
    ItemDescription,
    Spinner,
    Text,
} from '@posthog/quill'

import { ConversionRecordingsPage } from './conversionRecordingsLogic'

export function QuillConversionRecordingsModal({
    title,
    onClose,
    page,
    pageLoading,
    onLoadPage,
    queryError,
    playlist,
}: {
    title: string
    onClose: () => void
    page: ConversionRecordingsPage
    pageLoading: boolean
    onLoadPage: (pageIndex: number | undefined) => void
    queryError: JSX.Element | null
    playlist: JSX.Element
}): JSX.Element {
    return (
        <Dialog open onOpenChange={(open) => !open && onClose()}>
            <DialogContent size="wide">
                <DialogHeader>
                    <DialogTitle>{title}</DialogTitle>
                </DialogHeader>
                {/* A plain flex body, not the default scroll area, so the playlist shrinks to the space the dialog has. */}
                <DialogBody render={<div />} className="flex flex-col py-4">
                    <div className="flex min-h-0 flex-col gap-4">
                        <Text size="xs" variant="muted" render={<p className="m-0" />}>
                            Recordings from sessions where these conversions happened. Not every conversion has a
                            recording.
                        </Text>
                        {pageLoading && !page.session_ids.length && <Spinner />}
                        {page.preparing && (
                            <Item tone="info" size="sm">
                                <ItemContent>
                                    <ItemDescription>
                                        Conversion details are being prepared. Try again in a few minutes.
                                    </ItemDescription>
                                </ItemContent>
                            </Item>
                        )}
                        {queryError}
                        {page.session_ids.length > 0 ? (
                            <div data-not-quill className="h-[60vh] min-h-0 shrink overflow-auto">
                                {playlist}
                            </div>
                        ) : !pageLoading && !page.preparing && !page.errorMessage ? (
                            <Item tone="info" size="sm">
                                <ItemContent>
                                    <ItemDescription>
                                        These conversions have no session IDs. Try another date range or conversion
                                        goal.
                                    </ItemDescription>
                                </ItemContent>
                            </Item>
                        ) : null}
                        {page.preparing && (
                            <Button
                                variant="outline"
                                className="w-full"
                                loading={pageLoading}
                                onClick={() => onLoadPage(page.retryPage)}
                            >
                                Try again
                            </Button>
                        )}
                    </div>
                </DialogBody>
                {(page.pageIndex > 0 || page.has_more) && (
                    <DialogFooter className="flex-col sm:items-center">
                        <Text size="xs" variant="muted" render={<span className="m-0" />}>
                            {`Conversion sessions, page ${page.pageIndex + 1}`}
                        </Text>
                        <Button
                            variant="outline"
                            disabledReason={page.pageIndex === 0 ? 'You are on the first page' : undefined}
                            loading={pageLoading}
                            onClick={() => onLoadPage(page.pageIndex - 1)}
                        >
                            Previous
                        </Button>
                        <Button
                            variant="outline"
                            disabledReason={!page.has_more ? 'You are on the last page' : undefined}
                            loading={pageLoading}
                            onClick={() => onLoadPage(page.pageIndex + 1)}
                        >
                            Next
                        </Button>
                    </DialogFooter>
                )}
            </DialogContent>
        </Dialog>
    )
}
