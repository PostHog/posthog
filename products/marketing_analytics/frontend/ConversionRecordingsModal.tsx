import { useActions, useValues } from 'kea'

import { LemonBanner, LemonButton, LemonModal, Spinner } from '@posthog/lemon-ui'

import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { SessionRecordingsPlaylist } from 'scenes/session-recordings/playlist/SessionRecordingsPlaylist'
import { DEFAULT_RECORDING_FILTERS } from 'scenes/session-recordings/playlist/sessionRecordingsPlaylistLogic'

import { conversionRecordingsLogic } from './conversionRecordingsLogic'
import { MarketingQueryError } from './dashboard/MarketingQueryError'
import { ConversionRecordingsRequestApi } from './generated/api.schemas'
import { QuillConversionRecordingsModal } from './QuillConversionRecordingsModal'

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
    const todayRailNav = useFeatureFlag('TODAY_RAIL_NAV')

    const title = `${goalName}: conversion recordings for ${request.group || '(not set)'}`
    const queryError = page.errorMessage ? (
        <MarketingQueryError
            message={page.errorMessage}
            queryId={page.queryId}
            onRetry={() => loadSessions({ pageIndex: page.retryPage })}
            loading={pageLoading}
        />
    ) : null
    const playlist = (
        <SessionRecordingsPlaylist
            key={page.pageIndex}
            logicKey={`marketing-conversions-${JSON.stringify(request)}-${page.pageIndex}`}
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
                    No recordings are available for these conversion sessions. Try another date range or conversion
                    goal.
                </p>
            }
        />
    )

    if (todayRailNav) {
        return (
            <QuillConversionRecordingsModal
                title={title}
                onClose={onClose}
                page={page}
                pageLoading={pageLoading}
                onLoadPage={(pageIndex) => loadSessions({ pageIndex })}
                queryError={queryError}
                playlist={playlist}
            />
        )
    }

    return (
        <LemonModal
            isOpen
            onClose={onClose}
            title={title}
            width="90vw"
            footer={
                (page.pageIndex > 0 || page.has_more) && (
                    <>
                        <span className="text-secondary">Conversion sessions, page {page.pageIndex + 1}</span>
                        <LemonButton
                            type="secondary"
                            disabledReason={page.pageIndex === 0 ? 'You are on the first page' : undefined}
                            loading={pageLoading}
                            onClick={() => loadSessions({ pageIndex: page.pageIndex - 1 })}
                        >
                            Previous
                        </LemonButton>
                        <LemonButton
                            type="secondary"
                            disabledReason={!page.has_more ? 'You are on the last page' : undefined}
                            loading={pageLoading}
                            onClick={() => loadSessions({ pageIndex: page.pageIndex + 1 })}
                        >
                            Next
                        </LemonButton>
                    </>
                )
            }
        >
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
                {queryError}
                {page.session_ids.length > 0 ? (
                    <div className="h-[60vh] min-h-96 overflow-auto">{playlist}</div>
                ) : !pageLoading && !page.preparing && !page.errorMessage ? (
                    <LemonBanner type="info">
                        These conversions have no session IDs. Try another date range or conversion goal.
                    </LemonBanner>
                ) : null}
                {page.preparing && (
                    <LemonButton
                        type="secondary"
                        loading={pageLoading}
                        onClick={() => loadSessions({ pageIndex: page.retryPage })}
                        center
                        fullWidth
                    >
                        Try again
                    </LemonButton>
                )}
            </div>
        </LemonModal>
    )
}
