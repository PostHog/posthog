import { ReactNode } from 'react'

import { cn } from '@posthog/quill'

import { SidebarSection } from '~/layout/today/sidebar/SidebarSection'

import type { AnalyticsFragmentSectionApi } from './generated/api.schemas'

export interface SidebarLayoutSectionsProps {
    sections: AnalyticsFragmentSectionApi[]
    renderItem: (
        section: AnalyticsFragmentSectionApi,
        item: AnalyticsFragmentSectionApi['items'][number],
        index: number
    ) => JSX.Element[]
    renderIcon: (icon: NonNullable<AnalyticsFragmentSectionApi['icon']>) => JSX.Element | null
    isSectionOpen: (id: string) => boolean
    toggleSection: (id: string) => void
    dataAttrPrefix: string
    empty: ReactNode
}

export function SidebarLayoutSections({
    sections,
    renderItem,
    renderIcon,
    isSectionOpen,
    toggleSection,
    dataAttrPrefix,
    empty,
}: SidebarLayoutSectionsProps): JSX.Element {
    // The first heading needs no divider, even when filtering hides its rows.
    const firstHeadingId = sections.find((section) => section.title)?.id
    const visibleSections = sections
        .map((section) => ({ section, rows: section.items.flatMap((item, index) => renderItem(section, item, index)) }))
        .filter(({ rows }) => rows.length > 0)
    return (
        <>
            {visibleSections.length === 0
                ? empty
                : visibleSections.map(({ section, rows }, index) =>
                      section.title ? (
                          <SidebarSection
                              key={section.id}
                              label={section.title}
                              icon={section.icon ? renderIcon(section.icon) : null}
                              open={isSectionOpen(section.id)}
                              count={rows.length}
                              showCount={false}
                              onToggle={() => toggleSection(section.id)}
                              divider={section.id !== firstHeadingId}
                              dataAttr={`${dataAttrPrefix}-${section.id}`}
                          >
                              {rows}
                          </SidebarSection>
                      ) : (
                          <div
                              key={section.id}
                              className={cn('flex flex-col gap-px pb-2', index > 0 && 'border-t border-border pt-2')}
                          >
                              {rows}
                          </div>
                      )
                  )}
        </>
    )
}
