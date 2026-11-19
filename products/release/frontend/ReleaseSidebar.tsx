import { useValues } from 'kea'
import { router } from 'kea-router'
import { useState } from 'react'

import { IconCalendar, IconFlag, IconList, IconPlus } from '@posthog/icons'

import { removeProjectIdIfPresent } from 'lib/utils/kea-router'
import { urls } from 'scenes/urls'

import { iconForType } from '~/layout/panel-layout/ProjectTree/defaultTree'
import { escapePath } from '~/layout/panel-layout/ProjectTree/utils'
import { SidebarPinButton } from '~/layout/today/sidebar/SidebarPinButton'
import { sidebarPinsLogic } from '~/layout/today/sidebar/sidebarPinsLogic'
import { SidebarRow } from '~/layout/today/sidebar/SidebarRow'
import { SidebarSearchList } from '~/layout/today/sidebar/SidebarSearchList'
import { SidebarSection } from '~/layout/today/sidebar/SidebarSection'
import { newestByName } from '~/layout/today/todayNewestByName'
import { todayRecentsLogic } from '~/layout/today/todayRecentsLogic'
import { recentItemsModel } from '~/models/recentItemsModel'
import { FileSystemEntry, FileSystemIconType } from '~/queries/schema/schema-general'

import { releaseLogic } from './releaseLogic'
import { releaseSidebarEntryName, STAGE_COLOR_VARS } from './releaseUtils'

const RELEASE_TYPES = ['feature_flag', 'experiment', 'early_access_feature', 'release']
const RECENTS_LIMIT = 6

export function ReleaseSidebar(): JSX.Element {
    const { rows, flagCount, experimentCount, earlyAccessCount, dataLoading, releasesEnabled } = useValues(releaseLogic)
    const { shortcutData, pinnedShortcutIds } = useValues(sidebarPinsLogic)
    const { recents } = useValues(recentItemsModel)
    const { releaseRecents } = useValues(todayRecentsLogic)
    const { location } = useValues(router)
    const [query, setQuery] = useState('')
    const [closed, setClosed] = useState<Record<string, boolean>>({})
    const path = removeProjectIdIfPresent(location.pathname)
    const search = query.trim().toLowerCase()
    const matches = (label: string): boolean => !search || label.toLowerCase().includes(search)
    const toggle = (key: string): void => setClosed({ ...closed, [key]: !closed[key] })

    const releaseTypes = RELEASE_TYPES.filter((type) => type !== 'release' || releasesEnabled)
    const browse = [
        {
            key: 'all',
            label: 'View all',
            icon: <IconList />,
            to: urls.releases(),
            active: path === urls.releases(),
        },
        {
            key: 'calendar',
            label: 'Calendar',
            icon: <IconCalendar />,
            to: urls.releaseCalendar(),
            active: path === urls.releaseCalendar(),
        },
    ].filter((item) => (item.key !== 'calendar' || releasesEnabled) && matches(item.label))

    const products = [
        {
            key: 'releases',
            label: 'Releases',
            icon: <IconFlag />,
            to: urls.releaseList(),
            count: dataLoading && !rows.length ? undefined : rows.length,
            active: path === urls.releaseList(),
        },
        {
            key: 'flags',
            label: 'Feature flags',
            icon: iconForType('feature_flag' as FileSystemIconType),
            to: urls.featureFlags(),
            count: flagCount,
            active: path.startsWith(urls.featureFlags()),
        },
        {
            key: 'experiments',
            label: 'Experiments',
            icon: iconForType('experiment' as FileSystemIconType),
            to: urls.experiments(),
            count: experimentCount,
            active: path.startsWith('/experiments'),
        },
        {
            key: 'early-access',
            label: 'Early access features',
            icon: iconForType('early_access_feature' as FileSystemIconType),
            to: urls.earlyAccessFeatures(),
            count: earlyAccessCount,
            active: path.startsWith('/early_access_features'),
        },
    ].filter((item) => (item.key !== 'releases' || releasesEnabled) && matches(item.label))

    const releaseRowsById = new Map(rows.map((row) => [row.id, row]))
    const entryName = (entry: FileSystemEntry): string => releaseSidebarEntryName(entry, releaseRowsById) ?? ''
    const pinned = shortcutData.filter(
        (entry) =>
            !!entry.ref && releaseTypes.includes(entry.type ?? '') && !!entryName(entry) && matches(entryName(entry))
    )
    const releaseItems: FileSystemEntry[] = releaseRecents.flatMap((recent) => {
        const row = releaseRowsById.get(recent.id)
        return row
            ? [
                  {
                      id: row.id,
                      type: 'release',
                      ref: row.id,
                      path: escapePath(row.name),
                      href: urls.release(row.id),
                      last_viewed_at: new Date(recent.viewedAt).toISOString(),
                  },
              ]
            : []
    })
    const recent = newestByName(
        [...recents, ...releaseItems]
            .sort(
                (first, second) =>
                    (Date.parse(second.last_viewed_at ?? '') || 0) - (Date.parse(first.last_viewed_at ?? '') || 0)
            )
            .filter(
                (entry) =>
                    !!entry.ref &&
                    releaseTypes.includes(entry.type ?? '') &&
                    matches(entryName(entry)) &&
                    !pinnedShortcutIds.has(`${entry.type}:${entry.ref}`)
            ),
        entryName,
        (entry) => entry.id,
        RECENTS_LIMIT
    )

    const entryRow = (entry: FileSystemEntry, kind: 'pinned' | 'recent'): JSX.Element => (
        <SidebarRow
            key={`${kind}:${entry.id}`}
            value={`${kind}:${entry.id}`}
            label={entryName(entry)}
            icon={
                entry.type === 'release' ? (
                    <IconFlag />
                ) : (
                    iconForType((entry.type ?? 'feature_flag') as FileSystemIconType)
                )
            }
            to={entry.href ?? '#'}
            active={!!entry.href && path === removeProjectIdIfPresent(entry.href)}
            action={
                <SidebarPinButton
                    target={{
                        type: entry.type ?? '',
                        ref: entry.ref,
                        name: entry.type === 'release' ? 'Release' : entryName(entry),
                        href: entry.href,
                    }}
                    dataAttr={`release-sidebar-${kind}-pin`}
                />
            }
            dataAttr={`release-sidebar-${kind}`}
        />
    )

    return (
        <div
            className={`TodayPane group/colorful-product-icons colorful-product-icons-true ${STAGE_COLOR_VARS}`}
            data-quill
        >
            <SidebarSearchList
                query={query}
                onQueryChange={setQuery}
                searchLabel="Search releases"
                dataAttr="release-sidebar-search"
                listClassName="flex flex-col"
            >
                <div className="flex flex-col gap-px pb-2">
                    {browse.map((item) => (
                        <SidebarRow
                            key={item.key}
                            value={item.key}
                            label={item.label}
                            icon={item.icon}
                            to={item.to}
                            active={item.active}
                            dataAttr={`release-sidebar-${item.key}`}
                        />
                    ))}
                </div>
                {products.length > 0 && (
                    <div className="flex flex-col gap-px border-t border-border py-2">
                        {products.map((item) => (
                            <SidebarRow
                                key={item.key}
                                value={`product:${item.key}`}
                                label={item.label}
                                meta={item.count === undefined ? undefined : String(item.count)}
                                icon={item.icon}
                                to={item.to}
                                active={item.active}
                                dataAttr={`release-sidebar-${item.key}`}
                            />
                        ))}
                    </div>
                )}
                <SidebarSection
                    label="Pinned"
                    open={!closed.pinned}
                    count={pinned.length}
                    showCount={false}
                    onToggle={() => toggle('pinned')}
                    divider
                    dataAttr="release-section-pinned"
                >
                    {pinned.length ? (
                        pinned.map((entry) => entryRow(entry, 'pinned'))
                    ) : (
                        <SidebarRow
                            value="pinned:add"
                            label="Add a pinned item"
                            icon={<IconPlus />}
                            to={urls.releases()}
                            dataAttr="release-sidebar-pinned-add"
                        />
                    )}
                </SidebarSection>
                {recent.length > 0 && (
                    <SidebarSection
                        label="Recents"
                        open={!closed.recents}
                        count={recent.length}
                        showCount={false}
                        onToggle={() => toggle('recents')}
                        divider
                        dataAttr="release-section-recents"
                    >
                        {recent.map((entry) => entryRow(entry, 'recent'))}
                    </SidebarSection>
                )}
            </SidebarSearchList>
        </div>
    )
}
