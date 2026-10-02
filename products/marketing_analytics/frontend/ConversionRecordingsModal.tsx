import { useActions, useValues } from 'kea'

import { LemonBanner, LemonButton, LemonModal, Spinner } from '@posthog/lemon-ui'

import { SessionRecordingsPlaylist } from 'scenes/session-recordings/playlist/SessionRecordingsPlaylist'
import { DEFAULT_RECORDING_FILTERS } from 'scenes/session-recordings/playlist/sessionRecordingsPlaylistLogic'

import { conversionRecordingsLogic } from './conversionRecordingsLogic'
import { MarketingQueryError } from './dashboard/MarketingQueryError'
import { ConversionRecordingsRequestApi } from './generated/api.schemas'

export function ConversionRecordingsModal({
    request,
    goalName,
    onClose,
}: {
    request: ConversionRecordingsRequestApi
    goalName: string
    onClose: () => void
}): JSX.Element {
    const logic = conversionRecordingsLogic({ request })
    const { page, pageLoading } = useValues(logic)
    const { loadSessions } = useActions(logic)

    return (
        <LemonModal
            isOpen
            onClose={onClose}
            title={`${goalName}: conversion recordings for ${request.group || '(not set)'}`}
            width="90vw"
        >
            <LemonModal.Content>
                <div className="flex flex-col gap-4">
                    <p className="text-secondary m-0">
                        Recordings from sessions where these conversions happened. Not every conversion has a recording.
                    </p>
                    {pageLoading && !page.session_ids.length && <Spinner />}
                    {page.preparing && (
                        <LemonBanner type="info">
                            Conversion details are being prepared. Try again in a few minutes.
                        </LemonBanner>
                    )}
                    {page.failed && (
                        <MarketingQueryError
                            message="Couldn't load conversion recordings. Try again."
                            queryId={page.queryId}
                            onRetry={() => loadSessions({ append: page.has_more })}
                            loading={pageLoading}
                        />
                    )}
                    {page.session_ids.length > 0 ? (
                        <div className="h-[70vh] min-h-96">
                            <SessionRecordingsPlaylist
                                logicKey={`marketing-conversions-${JSON.stringify(request)}`}
                                analyticsSource="marketing-analytics-conversions"
                                autoPlay={false}
                                filters={{
                                    ...DEFAULT_RECORDING_FILTERS,
                                    session_ids: page.session_ids,
                                    date_from: 'all',
                                    date_to: null,
                                    duration: [],
                                    filter_test_accounts: false,
                                }}
                                resetToCallerFilters
                                updateSearchParams={false}
                                listEmptyState={
                                    <p className="p-4">
                                        No recordings are available for these conversion sessions. Try another date
                                        range or conversion goal.
                                    </p>
                                }
                            />
                        </div>
                    ) : !pageLoading && !page.preparing && !page.failed ? (
                        <LemonBanner type="info">
                            These conversions have no session IDs. Try another date range or conversion goal.
                        </LemonBanner>
                    ) : null}
                    {!page.failed && (page.has_more || page.preparing) && (
                        <LemonButton
                            type="secondary"
                            data-attr="conversion-recordings-load-more"
                            loading={pageLoading}
                            onClick={() => loadSessions({ append: page.has_more })}
                            center
                            fullWidth
                        >
                            {page.preparing ? 'Try again' : 'Load more conversion sessions'}
                        </LemonButton>
                    )}
                </div>
            </LemonModal.Content>
        </LemonModal>
    )
}
