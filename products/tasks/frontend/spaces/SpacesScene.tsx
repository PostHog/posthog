import { useActions, useValues } from 'kea'
import { ChangeEvent } from 'react'

import { IconChat, IconPlus, IconSearch } from '@posthog/icons'
import {
    Button,
    Empty,
    EmptyContent,
    EmptyDescription,
    EmptyHeader,
    EmptyMedia,
    EmptyTitle,
    Heading,
    InputGroup,
    InputGroupAddon,
    InputGroupInput,
    Skeleton,
    Text,
    TooltipProvider,
} from '@posthog/quill'

import { NotFound } from 'lib/components/NotFound'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { SceneExport } from 'scenes/sceneTypes'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'

import { ChannelDTOApi } from '../generated/api.schemas'
import { newSpaceLogic } from './newSpaceLogic'
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
    const { openNewSpace } = useActions(newSpaceLogic)

    if (!enabled) {
        return <NotFound object="page" />
    }
    // With nothing starred there is one list, so it needs no heading.
    const section = (label: string | null, spaces: ChannelDTOApi[]): JSX.Element | null =>
        spaces.length > 0 ? (
            <section className="flex flex-col gap-1" aria-label={label ?? 'Spaces'}>
                {label && (
                    <Heading size="sm" render={<h3 />} className="px-2 pb-1">
                        <span>{label}</span>{' '}
                        <Text render={<span />} size="sm" variant="muted" className="tabular-nums">
                            {spaces.length}
                        </Text>
                    </Heading>
                )}
                <div className="flex flex-col gap-px">
                    {spaces.map((space) => (
                        <SpacesIndexRow key={space.id} space={space} />
                    ))}
                </div>
            </section>
        ) : null

    return (
        <TooltipProvider>
            <SceneContent>
                <SceneTitleSection
                    name="Spaces"
                    resourceType={{ type: 'task' }}
                    actions={
                        <Button variant="primary" onClick={openNewSpace} data-attr="today-new-space-open-index">
                            <IconPlus />
                            New space…
                        </Button>
                    }
                />
                <div className="mx-auto flex w-full max-w-5xl flex-col gap-5" data-quill>
                    <InputGroup className="max-w-80">
                        <InputGroupInput
                            type="search"
                            placeholder="Search spaces…"
                            aria-label="Search spaces"
                            value={search}
                            onChange={(event: ChangeEvent<HTMLInputElement>) => setSearch(event.target.value)}
                            data-attr="today-spaces-index-search"
                        />
                        <InputGroupAddon>
                            <IconSearch />
                        </InputGroupAddon>
                    </InputGroup>
                    {spacesLoading && !sortedSpaces.length ? (
                        <div className="flex flex-col gap-px">
                            {[0, 1, 2, 3, 4, 5].map((row) => (
                                <Skeleton key={row} className="h-9 w-full" />
                            ))}
                        </div>
                    ) : spacesUnavailable && !sortedSpaces.length ? (
                        <Empty className="py-12">
                            <EmptyHeader>
                                <EmptyTitle>Spaces didn’t load</EmptyTitle>
                                <EmptyDescription>Check your connection and try again.</EmptyDescription>
                            </EmptyHeader>
                            <EmptyContent>
                                <Button
                                    variant="outline"
                                    loading={spacesLoading}
                                    onClick={() => loadSpaces()}
                                    data-attr="today-spaces-index-retry"
                                >
                                    Try again
                                </Button>
                            </EmptyContent>
                        </Empty>
                    ) : !lists.starred.length && !lists.rest.length ? (
                        <Empty className="py-12">
                            <EmptyHeader>
                                {!search && (
                                    <EmptyMedia variant="icon">
                                        <IconChat />
                                    </EmptyMedia>
                                )}
                                <EmptyTitle>{search ? 'No spaces match your search' : 'No spaces yet'}</EmptyTitle>
                                <EmptyDescription>
                                    {search
                                        ? 'Try a different name or repository.'
                                        : 'Spaces group the sessions you and your agents work on.'}
                                </EmptyDescription>
                            </EmptyHeader>
                            {!search && (
                                <EmptyContent>
                                    <Button
                                        variant="outline"
                                        onClick={openNewSpace}
                                        data-attr="today-new-space-open-empty"
                                    >
                                        <IconPlus />
                                        New space…
                                    </Button>
                                </EmptyContent>
                            )}
                        </Empty>
                    ) : (
                        <>
                            {section('Starred', lists.starred)}
                            {section(lists.starred.length ? 'Everything else' : null, lists.rest)}
                        </>
                    )}
                </div>
            </SceneContent>
        </TooltipProvider>
    )
}
