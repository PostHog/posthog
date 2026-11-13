import { useActions, useValues } from 'kea'
import { router } from 'kea-router'
import { useState } from 'react'

import { IconCalendar, IconList } from '@posthog/icons'

import { removeProjectIdIfPresent } from 'lib/utils/kea-router'
import { urls } from 'scenes/urls'

import { iconForType } from '~/layout/panel-layout/ProjectTree/defaultTree'
import { SidebarRow } from '~/layout/today/sidebar/SidebarRow'
import { SidebarSearchList } from '~/layout/today/sidebar/SidebarSearchList'
import { SidebarSection } from '~/layout/today/sidebar/SidebarSection'
import { FileSystemIconType } from '~/queries/schema/schema-general'

import { releaseLogic } from './releaseLogic'
import { ReleaseStageDot } from './ReleaseStageDot'
import { STAGE_COLOR_VARS } from './releaseUtils'

const SECTION_LIMIT = 10

export function ReleaseSidebar(): JSX.Element {
    const { rows, decisionRows, flagCount, experimentCount, earlyAccessCount } = useValues(releaseLogic)
    const { setDecisionOnly } = useActions(releaseLogic)
    const { location } = useValues(router)
    const [query, setQuery] = useState('')
    const [closed, setClosed] = useState<Record<string, boolean>>({})
    const path = removeProjectIdIfPresent(location.pathname)
    const search = query.trim().toLowerCase()
    const matches = (label: string): boolean => !search || label.toLowerCase().includes(search)
    const toggle = (key: string): void => setClosed({ ...closed, [key]: !closed[key] })
    const decisions = decisionRows.filter((row) => matches(row.name))
    const others = search ? rows.filter((row) => !row.needsDecision && matches(row.name)) : []
    const products = [
        {
            key: 'flags',
            label: 'Feature flags',
            to: urls.featureFlags(),
            type: 'feature_flag',
            count: flagCount,
            prefix: '/feature-flags',
        },
        {
            key: 'experiments',
            label: 'Experiments',
            to: urls.experiments(),
            type: 'experiment',
            count: experimentCount,
            prefix: '/experiments',
        },
        {
            key: 'early-access',
            label: 'Early access features',
            to: urls.earlyAccessFeatures(),
            type: 'early_access_feature',
            count: earlyAccessCount,
            prefix: '/early_access_features',
        },
    ].filter((product) => matches(product.label))

    const releaseRow = (row: (typeof rows)[number]): JSX.Element => (
        <SidebarRow
            key={row.id}
            value={`release:${row.id}`}
            label={row.name}
            icon={<ReleaseStageDot stage={row.stage} />}
            to={urls.release(row.id)}
            active={path === urls.release(row.id)}
            dataAttr="release-sidebar-release"
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
                    {matches('Calendar') && (
                        <SidebarRow
                            value="calendar"
                            label="Calendar"
                            icon={<IconCalendar />}
                            to={urls.releases()}
                            active={path === urls.releases()}
                            dataAttr="release-sidebar-calendar"
                        />
                    )}
                    {matches('Releases') && (
                        <SidebarRow
                            value="releases"
                            label="Releases"
                            meta={String(rows.length)}
                            icon={<IconList />}
                            to={urls.releaseList()}
                            active={path === urls.releaseList()}
                            dataAttr="release-sidebar-list"
                        />
                    )}
                </div>
                {decisions.length > 0 && (
                    <SidebarSection
                        label="Needs a decision"
                        open={!closed.decisions}
                        count={decisions.length}
                        onToggle={() => toggle('decisions')}
                        divider
                        dataAttr="release-section-decisions"
                    >
                        {decisions.slice(0, SECTION_LIMIT).map(releaseRow)}
                        {decisions.length > SECTION_LIMIT && (
                            <SidebarRow
                                value="decisions-all"
                                label={`Show all ${decisions.length}`}
                                to={urls.releaseList()}
                                onClick={() => setDecisionOnly(true)}
                                dataAttr="release-sidebar-decisions-all"
                            />
                        )}
                    </SidebarSection>
                )}
                {others.length > 0 && (
                    <SidebarSection
                        label="Other releases"
                        open
                        count={others.length}
                        onToggle={() => toggle('others')}
                        divider
                        dataAttr="release-section-others"
                    >
                        {others.slice(0, SECTION_LIMIT).map(releaseRow)}
                    </SidebarSection>
                )}
                {products.length > 0 && (
                    <div className="mt-auto">
                        <SidebarSection
                            label="Products"
                            open={!closed.products}
                            count={products.length}
                            showCount={false}
                            onToggle={() => toggle('products')}
                            divider
                            dataAttr="release-section-products"
                        >
                            {products.map((product) => (
                                <SidebarRow
                                    key={product.key}
                                    value={`product:${product.key}`}
                                    label={product.label}
                                    meta={String(product.count)}
                                    icon={iconForType(product.type as FileSystemIconType)}
                                    to={product.to}
                                    active={path.startsWith(product.prefix)}
                                    dataAttr={`release-sidebar-${product.key}`}
                                />
                            ))}
                        </SidebarSection>
                    </div>
                )}
            </SidebarSearchList>
        </div>
    )
}
