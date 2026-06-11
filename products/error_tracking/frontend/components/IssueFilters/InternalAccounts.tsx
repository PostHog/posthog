import { useActions, useValues } from 'kea'
import { ReactNode, useEffect } from 'react'

import { IconBolt, IconChevronRight, IconGear } from '@posthog/icons'
import { LemonButton, LemonMenu, LemonMenuItem, LemonMenuItems } from '@posthog/lemon-ui'

import {
    QuickFiltersModal,
    quickFiltersLogic,
    quickFiltersModalLogic,
    quickFiltersSectionLogic,
} from 'lib/components/QuickFilters'
import { filterTestAccountsDefaultsLogic } from 'scenes/settings/environment/filterTestAccountDefaultsLogic'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'

import { ErrorTrackingIssueAssignee, QuickFilterContext } from '~/queries/schema/schema-general'
import { QuickFilter } from '~/types'

import { AssigneeDropdown } from '../Assignee/AssigneeDropdown'
import { assigneeSelectLogic } from '../Assignee/assigneeSelectLogic'
import { issueQueryOptionsLogic } from '../IssueQueryOptions/issueQueryOptionsLogic'
import { issueFiltersLogic } from './issueFiltersLogic'
import { STATUS_OPTIONS, statusOptionLabel } from './Status'

interface FilterSettingsMenuProps {
    quickFilterContext?: QuickFilterContext
    logicKey?: string
    showIssueFilters?: boolean
    size?: 'xsmall' | 'small'
}

export const FilterSettingsMenu = (props: FilterSettingsMenuProps): JSX.Element => {
    const { showIssueFilters = true } = props
    // Conditionally render to avoid mounting issueQueryOptionsLogic
    // in contexts where it has no BindLogic (e.g. the issue detail scene)
    if (showIssueFilters) {
        return <FilterSettingsMenuWithIssueOptions {...props} />
    }
    return <FilterSettingsMenuCore {...props} issueFilterItems={[]} />
}

const FilterSettingsMenuWithIssueOptions = (props: FilterSettingsMenuProps): JSX.Element => {
    const { status, assignee, showQueryV3Switch, useQueryV3 } = useValues(issueQueryOptionsLogic)
    const { setStatus, setAssignee, setUseQueryV3 } = useActions(issueQueryOptionsLogic)

    const issueFilterItems: LemonMenuItem[] = [
        {
            label: 'Status',
            sideIcon: <IconChevronRight className="size-3" />,
            trigger: 'hover',
            items: STATUS_OPTIONS.map((option) => ({
                label: statusOptionLabel(option),
                active: (status ?? 'active') === option,
                onClick: () => setStatus(option),
            })),
        },
        {
            label: 'Assignee',
            sideIcon: <IconChevronRight className="size-3" />,
            trigger: 'hover',
            custom: true,
            items: [
                {
                    label: () => (
                        <AssigneeSubmenu assignee={assignee ?? null} onChange={(value) => setAssignee(value)} />
                    ),
                },
            ],
        },
        ...(showQueryV3Switch
            ? [
                  {
                      label: 'v3 query',
                      tooltip: 'Use denormalized ClickHouse table (no Postgres joins)',
                      active: useQueryV3,
                      onClick: () => setUseQueryV3(!useQueryV3),
                  },
              ]
            : []),
    ]

    return <FilterSettingsMenuCore {...props} issueFilterItems={issueFilterItems} />
}

const FilterSettingsMenuCore = ({
    quickFilterContext,
    logicKey,
    issueFilterItems,
    size = 'small',
}: FilterSettingsMenuProps & {
    issueFilterItems: LemonMenuItem[]
}): JSX.Element => {
    const { filterTestAccounts } = useValues(issueFiltersLogic)
    const { setFilterTestAccounts } = useActions(issueFiltersLogic)
    const { currentTeam } = useValues(teamLogic)
    const hasFilters = (currentTeam?.test_account_filters || []).length > 0
    const { setLocalDefault } = useActions(filterTestAccountsDefaultsLogic)

    const { quickFilters } = useValues(
        quickFiltersLogic({ context: quickFilterContext || QuickFilterContext.ErrorTrackingIssueFilters })
    )
    const { selectedQuickFilters } = useValues(
        quickFiltersSectionLogic({
            context: quickFilterContext || QuickFilterContext.ErrorTrackingIssueFilters,
            logicKey,
        })
    )
    const { setQuickFilterValue, clearQuickFilter } = useActions(
        quickFiltersSectionLogic({
            context: quickFilterContext || QuickFilterContext.ErrorTrackingIssueFilters,
            logicKey,
        })
    )

    const checked = hasFilters ? filterTestAccounts : false

    const toggle = (): void => {
        if (hasFilters) {
            setFilterTestAccounts(!filterTestAccounts)
            setLocalDefault(!filterTestAccounts)
        }
    }

    const quickFilterItems: LemonMenuItem[] = !quickFilterContext
        ? []
        : quickFilters.length === 0
          ? [
                {
                    label: 'Set up quick filters',
                    onClick: () => quickFiltersModalLogic({ context: quickFilterContext }).actions.openModal(),
                },
            ]
          : quickFilters.map((filter: QuickFilter) => {
                const selectedFilter = selectedQuickFilters[filter.id]
                const selectedOptionId = selectedFilter?.optionId || null

                if (filter.options.length === 1) {
                    const option = filter.options[0]
                    const isActive = selectedOptionId === option.id
                    return {
                        label: filter.name,
                        active: isActive,
                        onClick: () =>
                            isActive
                                ? clearQuickFilter(filter.id)
                                : setQuickFilterValue(filter.id, filter.property_name, option),
                    }
                }

                return {
                    label: filter.name,
                    sideIcon: <IconChevronRight className="size-3" />,
                    trigger: 'hover' as const,
                    items: filter.options.map((option) => ({
                        label: option.label,
                        active: selectedOptionId === option.id,
                        onClick: () => setQuickFilterValue(filter.id, filter.property_name, option),
                    })),
                }
            })

    const sectionTitle = (label: string, onClick: () => void): ReactNode => (
        <h5 className="mx-2 my-1 flex items-center justify-between">
            {label}
            <LemonButton size="xsmall" icon={<IconGear />} onClick={onClick} noPadding />
        </h5>
    )

    const items: LemonMenuItems = [
        ...(issueFilterItems.length > 0 ? [{ title: 'Issue', items: issueFilterItems }] : []),
        ...(quickFilterItems.length > 0
            ? [
                  {
                      title: quickFilterContext
                          ? sectionTitle('Quick filters', () => {
                                quickFiltersModalLogic({ context: quickFilterContext }).actions.openModal()
                            })
                          : 'Quick filters',
                      items: quickFilterItems,
                  },
              ]
            : []),
        {
            title: sectionTitle('Internal users', () => {
                window.open(urls.settings('project-product-analytics', 'internal-user-filtering'), '_blank')
            }),
            items: [
                {
                    label: 'Filter out internal users',
                    active: checked,
                    onClick: toggle,
                    disabledReason: !hasFilters ? "You haven't set any internal and test filters" : undefined,
                },
            ],
        },
    ]

    return (
        <>
            <LemonMenu items={items} trigger="hover">
                <LemonButton type="tertiary" size={size} icon={<IconBolt />} />
            </LemonMenu>
            {quickFilterContext && <QuickFiltersModal context={quickFilterContext} />}
        </>
    )
}

const AssigneeSubmenu = ({
    assignee,
    onChange,
}: {
    assignee: ErrorTrackingIssueAssignee | null
    onChange: (assignee: ErrorTrackingIssueAssignee | null) => void
}): JSX.Element => {
    const { ensureAssigneeTypesLoaded, setSearch } = useActions(assigneeSelectLogic)

    useEffect(() => {
        ensureAssigneeTypesLoaded()
    }, [ensureAssigneeTypesLoaded])

    return (
        <AssigneeDropdown
            assignee={assignee}
            onChange={(value) => {
                setSearch('')
                onChange(value)
            }}
        />
    )
}
