import { useActions, useValues } from 'kea'

import { IconSearch } from '@posthog/icons'
import { LemonButton, LemonInput, Spinner } from '@posthog/lemon-ui'

import { NotFound } from 'lib/components/NotFound'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { SceneExport } from 'scenes/sceneTypes'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'

import { SpacesIndexRow } from './SpacesIndexRow'
import { spacesSceneLogic } from './spacesSceneLogic'

export const scene: SceneExport = {
    component: SpacesScene,
    logic: spacesSceneLogic,
}

export function SpacesScene(): JSX.Element {
    const enabled = useFeatureFlag('TODAY_RAIL_NAV')
    const { lists, search, spacesLoading, spacesUnavailable, sortedSpaces } = useValues(spacesSceneLogic)
    const { setSearch, loadSpaces } = useActions(spacesSceneLogic)

    if (!enabled) {
        return <NotFound object="page" />
    }
    return (
        <SceneContent>
            <SceneTitleSection name="Spaces" resourceType={{ type: 'task' }} />
            <div className="mx-auto flex w-full max-w-5xl flex-col gap-5">
                <LemonInput
                    type="search"
                    className="max-w-80"
                    prefix={<IconSearch />}
                    placeholder="Search spaces…"
                    aria-label="Search spaces"
                    value={search}
                    onChange={setSearch}
                    data-attr="today-spaces-index-search"
                />
                {spacesLoading && !sortedSpaces.length ? (
                    <Spinner />
                ) : spacesUnavailable && !sortedSpaces.length ? (
                    <div className="flex flex-col items-start gap-2 text-secondary">
                        <span>Spaces didn’t load.</span>
                        <LemonButton size="small" type="secondary" onClick={() => loadSpaces()}>
                            Try again
                        </LemonButton>
                    </div>
                ) : !lists.starred.length && !lists.rest.length ? (
                    <span className="text-secondary">{search ? 'No spaces match your search.' : 'No spaces yet.'}</span>
                ) : (
                    <>
                        {lists.starred.length > 0 && (
                            <section className="flex flex-col gap-1" aria-label="Starred">
                                <h3 className="mb-1 text-xs font-semibold uppercase text-secondary">
                                    Starred <span className="font-normal">{lists.starred.length}</span>
                                </h3>
                                {lists.starred.map((space) => (
                                    <SpacesIndexRow key={space.id} space={space} />
                                ))}
                            </section>
                        )}
                        {lists.rest.length > 0 && (
                            <section className="flex flex-col gap-1" aria-label="All spaces">
                                <h3 className="mb-1 text-xs font-semibold uppercase text-secondary">
                                    All spaces <span className="font-normal">{lists.rest.length}</span>
                                </h3>
                                {lists.rest.map((space) => (
                                    <SpacesIndexRow key={space.id} space={space} />
                                ))}
                            </section>
                        )}
                    </>
                )}
            </div>
        </SceneContent>
    )
}
