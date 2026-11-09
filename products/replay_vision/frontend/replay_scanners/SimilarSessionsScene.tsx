import { useActions, useValues } from 'kea'

import { LemonButton, LemonSkeleton, Link } from '@posthog/lemon-ui'

import { pluralize } from 'lib/utils/strings'
import { SceneExport } from 'scenes/sceneTypes'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'
import { ProductKey } from '~/queries/schema/schema-general'

import { highlightFeedBreadcrumb } from '../utils/breadcrumbs'
import { SimilarSessionRow } from './components/SimilarSessionRow'
import { similarSessionsSceneLogic } from './similarSessionsSceneLogic'

export const scene: SceneExport = {
    component: SimilarSessionsScene,
    logic: similarSessionsSceneLogic,
    productKey: ProductKey.REPLAY_VISION,
}

const BACK_TO_FEED = (
    <Link to={highlightFeedBreadcrumb().path} data-attr="vision-similar-sessions-back">
        Go back to Highlights
    </Link>
)

export function SimilarSessionsScene(): JSX.Element {
    const { query, sessions, sessionsLoading, sessionsFailed, moreFailed } = useValues(similarSessionsSceneLogic)
    const { loadSessions, loadMoreSessions } = useActions(similarSessionsSceneLogic)

    return (
        <SceneContent>
            <SceneTitleSection
                name="Similar sessions"
                description="Sessions the Highlights feed groups as near duplicates of each other."
                resourceType={{ type: 'replay_vision' }}
            />
            <div className="@container/similar-sessions mx-auto flex w-full max-w-5xl flex-col gap-3">
                {!query?.scannerId ? (
                    <p className="m-0 text-sm text-secondary">
                        This link is incomplete. Open the similar sessions again from a Highlights card. {BACK_TO_FEED}
                    </p>
                ) : sessions === null && sessionsFailed ? (
                    <div className="flex items-center gap-2 rounded border p-4 text-sm text-secondary">
                        <span>Couldn't load the similar sessions.</span>
                        <LemonButton size="small" type="secondary" onClick={() => loadSessions()}>
                            Try again
                        </LemonButton>
                    </div>
                ) : sessions === null ? (
                    <div className="flex flex-col gap-3" aria-busy>
                        {Array.from({ length: 3 }, (_, i) => (
                            <LemonSkeleton key={i} className="h-40 rounded-lg" />
                        ))}
                    </div>
                ) : sessions.results.length === 0 ? (
                    <p className="m-0 text-sm text-secondary">
                        No similar sessions in this date range. They may have been dismissed or aged out of the feed.{' '}
                        {BACK_TO_FEED}
                    </p>
                ) : (
                    <>
                        <p className="m-0 text-sm text-secondary">{pluralize(sessions.count, 'session')}</p>
                        <ul className="m-0 flex list-none flex-col gap-3 p-0">
                            {sessions.results.map((session) => (
                                <SimilarSessionRow
                                    key={session.id}
                                    observation={session}
                                    groupObservationId={query.observationId}
                                />
                            ))}
                        </ul>
                        {moreFailed ? (
                            <div className="flex items-center gap-2 text-sm text-secondary">
                                <span>Couldn't load more sessions.</span>
                                <LemonButton size="small" type="secondary" onClick={() => loadMoreSessions()}>
                                    Try again
                                </LemonButton>
                            </div>
                        ) : (
                            sessions.results.length < sessions.count && (
                                <LemonButton
                                    type="secondary"
                                    className="self-center"
                                    onClick={() => loadMoreSessions()}
                                    loading={sessionsLoading}
                                    data-attr="vision-similar-sessions-load-more"
                                >
                                    Show more sessions
                                </LemonButton>
                            )
                        )}
                    </>
                )}
            </div>
        </SceneContent>
    )
}
