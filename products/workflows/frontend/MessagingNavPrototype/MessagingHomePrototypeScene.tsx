// PROTOTYPE, never merged: PostHog/michaelr-context#419 and #421. The Email & Messaging home under /messaging. #419
// settled the navigation (the in-scene sidebar, shape A); #421 adds saved views, tags and search in three variants.
import { useValues } from 'kea'
import { router } from 'kea-router'
import { useState } from 'react'

import { IconGlobe, IconPin, IconSearch, IconUser } from '@posthog/icons'
import { LemonButton, LemonDivider, LemonInput } from '@posthog/lemon-ui'

import { removeProjectIdIfPresent } from 'lib/utils/kea-router'
import { SceneExport } from 'scenes/sceneTypes'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'
import { messagingNavPrototypeLogic } from '~/layout/today/messagingNavPrototype/messagingNavPrototypeLogic'
import {
    MESSAGING_HOME_PATH,
    MESSAGING_NAV_GROUPS,
    MESSAGING_PRODUCT_NAME,
    MESSAGING_SECTION_ICONS,
    MESSAGING_SECTION_LABELS,
    MESSAGING_SECTION_META,
    MessagingSection,
    messagingSectionForPath,
    messagingSectionUrl,
} from '~/layout/today/messagingNavPrototype/messagingNavPrototypeNav'
import { MessagingNavPrototypeNewButton } from '~/layout/today/messagingNavPrototype/MessagingNavPrototypeNewButton'

import { MESSAGING_SECTION_CONTENT } from './MessagingHomePrototypeSections'
import { MESSAGING_SEARCH_PATH, MessagingSearchResults } from './views/MessagingSearchResults'
import { ViewsPrototypeList, savedViewUrl } from './views/ViewsPrototypeList'
import { DefaultViewKey, SavedView, itemsFor, useViewsState } from './views/viewsPrototypeStore'

export const scene: SceneExport = {
    component: MessagingHomePrototypeScene,
}

const VIEW_SECTIONS: MessagingSection[] = ['broadcasts', 'transactional', 'workflows']

/** Which page a /messaging path opens: a sidebar section, a saved view, every message, or the search results. */
type MessagingPage =
    | { kind: 'section'; section: MessagingSection }
    | { kind: 'view'; id: string }
    | { kind: 'all' }
    | { kind: 'search' }

function pageForPath(pathname: string): MessagingPage {
    const segment = removeProjectIdIfPresent(pathname)
        .slice(MESSAGING_HOME_PATH.length + 1)
        .split('/')[0]
    if (segment.startsWith('view-')) {
        return { kind: 'view', id: segment.slice(5) }
    }
    if (segment === 'all') {
        return { kind: 'all' }
    }
    if (segment === 'search') {
        return { kind: 'search' }
    }
    return { kind: 'section', section: messagingSectionForPath(pathname) ?? 'broadcasts' }
}

function SidebarRow({
    icon,
    label,
    meta,
    active,
    to,
    dataAttr,
}: {
    icon: JSX.Element
    label: string
    meta?: string
    active: boolean
    to: string
    dataAttr: string
}): JSX.Element {
    return (
        <LemonButton
            size="small"
            fullWidth
            icon={icon}
            active={active}
            to={to}
            sideIcon={meta ? <span className="text-xs font-normal text-secondary">{meta}</span> : undefined}
            data-attr={dataAttr}
        >
            <span className="truncate">{label}</span>
        </LemonButton>
    )
}

function SavedViewRow({ view, active, pinned }: { view: SavedView; active: boolean; pinned?: boolean }): JSX.Element {
    const state = useViewsState()
    return (
        <SidebarRow
            icon={pinned ? <IconPin /> : view.visibility === 'private' ? <IconUser /> : <IconGlobe />}
            label={view.name}
            meta={String(itemsFor(state, view.query).length)}
            active={active}
            to={savedViewUrl(view.id)}
            dataAttr="messaging-prototype-saved-view-row"
        />
    )
}

function SidebarSearch(): JSX.Element {
    const [text, setText] = useState('')
    return (
        <LemonInput
            type="search"
            size="small"
            placeholder="Search messages"
            value={text}
            onChange={setText}
            onPressEnter={() => {
                router.actions.push(MESSAGING_SEARCH_PATH, { q: text })
                setText('')
            }}
            className="mb-2"
            data-attr="messaging-prototype-sidebar-search"
        />
    )
}

/** Shape A from #419: the home brings its own sidebar inside the scene. #421 adds the saved views to it. */
function InSceneSidebar({ page }: { page: MessagingPage }): JSX.Element {
    const state = useViewsState()
    const variant = state.variant
    const activeSection = page.kind === 'section' ? page.section : null
    return (
        <nav className="flex w-60 shrink-0 flex-col gap-px" aria-label={MESSAGING_PRODUCT_NAME}>
            {variant === 'A' && <SidebarSearch />}
            {MESSAGING_NAV_GROUPS.map((group, index) => (
                <div key={index} className="flex flex-col gap-px">
                    {group.label ? (
                        <div className="mt-3 mb-1 px-2 text-xxs font-semibold uppercase tracking-wide text-secondary">
                            {group.label}
                        </div>
                    ) : (
                        index > 0 && <LemonDivider className="my-2" />
                    )}
                    {variant === 'C' && group.label === 'Views' && (
                        <SidebarRow
                            icon={<IconSearch />}
                            label="All messages"
                            active={page.kind === 'all'}
                            to={`${MESSAGING_HOME_PATH}/all`}
                            dataAttr="messaging-prototype-scene-row-all"
                        />
                    )}
                    {group.sections.map((section) => (
                        <SidebarRow
                            key={section}
                            icon={MESSAGING_SECTION_ICONS[section]}
                            label={MESSAGING_SECTION_LABELS[section]}
                            meta={MESSAGING_SECTION_META[section]}
                            active={activeSection === section}
                            to={messagingSectionUrl(section)}
                            dataAttr={`messaging-prototype-scene-row-${section}`}
                        />
                    ))}
                    {variant === 'C' &&
                        group.label === 'Views' &&
                        state.savedViews.map((view) => (
                            <SavedViewRow
                                key={view.id}
                                view={view}
                                active={page.kind === 'view' && page.id === view.id}
                                pinned
                            />
                        ))}
                    {variant === 'A' && group.label === 'Views' && (
                        <>
                            {state.savedViews.map((view) => (
                                <SavedViewRow
                                    key={view.id}
                                    view={view}
                                    active={page.kind === 'view' && page.id === view.id}
                                />
                            ))}
                            {state.savedViews.length === 0 && (
                                <div className="px-2 text-xs text-secondary">
                                    Filter a view, then save it to see it here.
                                </div>
                            )}
                        </>
                    )}
                </div>
            ))}
        </nav>
    )
}

function PageContent({ page }: { page: MessagingPage }): JSX.Element {
    if (page.kind === 'view') {
        return <ViewsPrototypeList key={page.id} list={null} viewId={page.id} />
    }
    if (page.kind === 'all') {
        return <ViewsPrototypeList list="all" />
    }
    if (page.kind === 'search') {
        return <MessagingSearchResults />
    }
    if (VIEW_SECTIONS.includes(page.section)) {
        return <ViewsPrototypeList key={page.section} list={page.section as DefaultViewKey} />
    }
    const Content = MESSAGING_SECTION_CONTENT[page.section]
    return <Content />
}

function pageTitle(page: MessagingPage, savedViews: SavedView[]): string {
    switch (page.kind) {
        case 'view':
            return savedViews.find((v) => v.id === page.id)?.name ?? 'View not found'
        case 'all':
            return 'All messages'
        case 'search':
            return 'Search'
        case 'section':
            return MESSAGING_SECTION_LABELS[page.section]
    }
}

export function MessagingHomePrototypeScene(): JSX.Element {
    const { location } = useValues(router)
    const { variant } = useValues(messagingNavPrototypeLogic)
    const { savedViews } = useViewsState()
    const page = pageForPath(location.pathname)
    const inScene = variant === 'A'
    const title = pageTitle(page, savedViews)

    return (
        <SceneContent>
            <SceneTitleSection
                // With the pane in the app sidebar, the pane names the product and the page names the row.
                name={inScene ? MESSAGING_PRODUCT_NAME : title}
                description={
                    inScene ? 'Broadcasts, transactional emails and messaging workflows, with their setup.' : undefined
                }
                resourceType={{ type: 'transactional' }}
                actions={<MessagingNavPrototypeNewButton inline />}
            />
            {inScene ? (
                <div className="flex gap-6">
                    <InSceneSidebar page={page} />
                    <div className="flex min-w-0 flex-1 flex-col gap-3">
                        <h2 className="m-0 text-lg font-semibold">{title}</h2>
                        <PageContent page={page} />
                    </div>
                </div>
            ) : (
                <PageContent page={page} />
            )}
        </SceneContent>
    )
}
