import { useActions, useValues } from 'kea'

import { IconFilter } from '@posthog/icons'
import { LemonButton, LemonMenu } from '@posthog/lemon-ui'

import { QuickFilterContext } from '~/queries/schema/schema-general'

import { ErrorFilters } from 'products/error_tracking/frontend/components/IssueFilters'
import {
    ORDER_BY_OPTIONS,
    issueQueryOptionsLogic,
} from 'products/error_tracking/frontend/components/IssueQueryOptions/issueQueryOptionsLogic'

import { ERROR_TRACKING_SCENE_LOGIC_KEY } from '../../errorTrackingSceneLogic'

const QUICK_FILTER_CONTEXT = QuickFilterContext.ErrorTrackingIssueFilters

export function IssuesFilters({ reload }: { reload?: React.ReactNode }): JSX.Element {
    const { orderBy, orderDirection } = useValues(issueQueryOptionsLogic)
    const { setOrderBy, setOrderDirection } = useActions(issueQueryOptionsLogic)

    return (
        <ErrorFilters.Root>
            <ErrorFilters.SearchBar>
                {reload && (
                    <>
                        <div className="flex items-stretch rounded-l-full overflow-hidden">{reload}</div>
                        <ErrorFilters.SearchBarDivider />
                    </>
                )}
                <div className="flex items-stretch overflow-hidden">
                    <ErrorFilters.DateRange type="tertiary" />
                </div>
                <ErrorFilters.SearchBarDivider />
                <div className="flex items-stretch overflow-hidden">
                    <ErrorFilters.SettingsMenu
                        quickFilterContext={QUICK_FILTER_CONTEXT}
                        logicKey={ERROR_TRACKING_SCENE_LOGIC_KEY}
                    />
                </div>
                <ErrorFilters.SearchBarDivider />
                <div className="flex-1 overflow-hidden">
                    <ErrorFilters.FilterGroup
                        quickFilterContext={QUICK_FILTER_CONTEXT}
                        logicKey={ERROR_TRACKING_SCENE_LOGIC_KEY}
                    />
                </div>
                <ErrorFilters.SearchBarDivider />
                <div className="flex items-stretch overflow-hidden">
                    <LemonMenu
                        items={Object.entries(ORDER_BY_OPTIONS).map(([value, label]) => ({
                            label,
                            active: orderBy === value,
                            onClick: () => setOrderBy(value as typeof orderBy),
                        }))}
                    >
                        <LemonButton type="tertiary" size="small" icon={<IconFilter />}>
                            {ORDER_BY_OPTIONS[orderBy]}
                        </LemonButton>
                    </LemonMenu>
                </div>
                <ErrorFilters.SearchBarDivider />
                <div className="flex items-stretch rounded-r-full overflow-hidden">
                    <LemonButton
                        type="tertiary"
                        size="small"
                        onClick={() => setOrderDirection(orderDirection === 'ASC' ? 'DESC' : 'ASC')}
                    >
                        <span className="text-xs px-1">{orderDirection}</span>
                    </LemonButton>
                </div>
            </ErrorFilters.SearchBar>
        </ErrorFilters.Root>
    )
}
