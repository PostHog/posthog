import { ReactNode } from 'react'

import type { SidebarSectionApi } from './generated/api.schemas'
import { SidebarSection } from './primitives/SidebarSection'

export interface SidebarLayoutSectionsProps {
    sections: SidebarSectionApi[]
    renderItem: (section: SidebarSectionApi, item: SidebarSectionApi['items'][number], index: number) => JSX.Element[]
    renderIcon: (icon: NonNullable<SidebarSectionApi['icon']>) => JSX.Element | null
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
                : visibleSections.map(({ section, rows }) =>
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
                          <div key={section.id} className="flex flex-col gap-px pb-2">
                              {rows}
                          </div>
                      )
                  )}
        </>
    )
}
