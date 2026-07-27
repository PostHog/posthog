import { BindLogic, useActions, useValues } from 'kea'

import { IconCheck } from '@posthog/icons'
import { LemonButton, Spinner } from '@posthog/lemon-ui'

import { EmptyMessage } from 'lib/components/EmptyMessage/EmptyMessage'
import { sessionPlayerModalLogic } from 'scenes/session-recordings/player/modal/sessionPlayerModalLogic'
import { SessionRecordingPreview } from 'scenes/session-recordings/playlist/SessionRecordingPreview'
import {
    SessionRecordingPlaylistLogicProps,
    sessionRecordingsPlaylistLogic,
} from 'scenes/session-recordings/playlist/sessionRecordingsPlaylistLogic'

import { RecordingUniversalFilters } from '~/types'

import { MessageTemplate } from '../../../messages/MessageTemplate'
import { RecordingsFiltersSummary } from './RecordingsFiltersSummary'

export function RecordingsWidget({
    toolCallId,
    filters,
    embedded = false,
    onAcceptFilters,
}: {
    toolCallId: string
    filters: RecordingUniversalFilters
    embedded?: boolean
    /** When provided, renders an "accept these filters" bar under the list. Consumer-specific. */
    onAcceptFilters?: ((filters: RecordingUniversalFilters) => void) | null
}): JSX.Element {
    const logicProps: SessionRecordingPlaylistLogicProps = {
        logicKey: `ai-recordings-widget-${toolCallId}`,
        filters,
        updateSearchParams: false,
        autoPlay: false,
        // Handle a failed query inline (see RecordingsListContent) rather than raising a global
        // toast with the raw backend error — an AI-generated filter can produce an invalid query.
        suppressErrorToast: true,
    }
    const content = (
        <>
            <RecordingsFiltersSummary filters={filters} />
            <RecordingsListContent />
            {onAcceptFilters && <AcceptFiltersBar filters={filters} onAccept={onAcceptFilters} />}
        </>
    )

    return (
        <BindLogic logic={sessionRecordingsPlaylistLogic} props={logicProps}>
            {embedded ? (
                <div className="overflow-hidden rounded border bg-surface-primary">{content}</div>
            ) : (
                <MessageTemplate type="ai" wrapperClassName="w-full" boxClassName="p-0 overflow-hidden">
                    {content}
                </MessageTemplate>
            )}
        </BindLogic>
    )
}

function AcceptFiltersBar({
    filters,
    onAccept,
}: {
    filters: RecordingUniversalFilters
    onAccept: (filters: RecordingUniversalFilters) => void
}): JSX.Element {
    return (
        <div className="border-t px-3 py-2 flex items-center justify-end">
            <LemonButton type="primary" size="small" icon={<IconCheck />} onClick={() => onAccept(filters)}>
                Use these filters for session analysis
            </LemonButton>
        </div>
    )
}

function RecordingsListContent(): JSX.Element {
    const { otherRecordings, sessionRecordingsResponseLoading, sessionRecordingsAPIErrored, hasNext } =
        useValues(sessionRecordingsPlaylistLogic)
    const { maybeLoadSessionRecordings } = useActions(sessionRecordingsPlaylistLogic)
    const { openSessionPlayer } = useActions(sessionPlayerModalLogic())

    const hasRecordings = otherRecordings.length > 0

    return (
        <div className="border-t *:not-first:border-t max-h-80 overflow-y-auto">
            {sessionRecordingsResponseLoading && !hasRecordings ? (
                <div className="flex items-center justify-center gap-2 py-12 text-muted">
                    <Spinner textColored />
                    <span>Loading recordings...</span>
                </div>
            ) : sessionRecordingsAPIErrored && !hasRecordings ? (
                <div className="py-2">
                    <EmptyMessage
                        title="Couldn't load recordings"
                        description="These filters couldn't be applied. Try rephrasing your request or adjusting the filters."
                    />
                </div>
            ) : !hasRecordings ? (
                <div className="py-2">
                    <EmptyMessage title="No recordings found" description="No recordings match the specified filters" />
                </div>
            ) : (
                <>
                    {otherRecordings.map((recording) => (
                        <div
                            key={recording.id}
                            onClick={(e) => {
                                e.preventDefault()
                                openSessionPlayer(recording)
                            }}
                        >
                            <SessionRecordingPreview recording={recording} selectable={false} />
                        </div>
                    ))}
                    {hasNext && (
                        <div className="p-2">
                            <LemonButton
                                fullWidth
                                type="secondary"
                                size="small"
                                onClick={() => maybeLoadSessionRecordings('older')}
                                loading={sessionRecordingsResponseLoading}
                            >
                                Load more recordings
                            </LemonButton>
                        </div>
                    )}
                </>
            )}
        </div>
    )
}
