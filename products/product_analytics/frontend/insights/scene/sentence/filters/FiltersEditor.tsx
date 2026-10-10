import { BindLogic, useActions, useValues } from 'kea'
import { useId } from 'react'

import { IconPlus } from '@posthog/icons'
import {
    Button,
    Field,
    FieldContent,
    FieldDescription,
    FieldLabel,
    Separator,
    Skeleton,
    Switch,
    Text,
} from '@posthog/quill'

import type { InsightLogicProps } from '~/types'

import { FilterGroupCard } from './FilterGroupCard'
import { FilterGroupRows } from './FilterGroupRows'
import { filtersEditorLogic } from './filtersEditorLogic'
import { INSIGHT_FILTERS_TARGET } from './filtersTarget'
import type { FiltersTarget } from './filtersTarget'
import { MatchModeToggle } from './MatchModeToggle'

export interface FiltersEditorProps {
    insightProps: InsightLogicProps
    /** The filters to edit. The filters of the whole insight when not set. */
    target?: FiltersTarget
}

export function FiltersEditor({ insightProps, target = INSIGHT_FILTERS_TARGET }: FiltersEditorProps): JSX.Element {
    const logicProps = { insightProps, target }
    const logic = filtersEditorLogic(logicProps)
    const {
        status,
        filterGroups,
        showGroups,
        groupsMatchMode,
        canAddGroup,
        filterTestAccounts,
        hasTestAccountFilters,
    } = useValues(logic)
    const { addGroup, setGroupsMatchMode, setFilterTestAccounts } = useActions(logic)
    const testAccountsId = useId()
    const editsOneEvent = target.kind === 'series'

    if (status === 'loading') {
        return (
            <div className="flex flex-col gap-2" aria-busy="true" data-attr="quill-insight-filters-loading">
                <Skeleton className="h-7 w-full" />
                <Skeleton className="h-7 w-2/3" />
            </div>
        )
    }

    if (status === 'unavailable') {
        return (
            <Text size="sm" variant="muted" data-attr="quill-insight-filters-unavailable">
                {editsOneEvent
                    ? 'This event is no longer part of the insight.'
                    : 'This kind of insight has no filters to edit here.'}
            </Text>
        )
    }

    const addGroupButton = canAddGroup && (
        <Button variant="outline" onClick={() => addGroup()} data-attr="quill-insight-filters-add-group">
            <IconPlus />
            Add filter group
        </Button>
    )

    return (
        <BindLogic logic={filtersEditorLogic} props={logicProps}>
            <div className="flex flex-col gap-4" data-attr="quill-insight-filters-editor">
                {showGroups ? (
                    <>
                        <div className="flex flex-col gap-2">
                            <MatchModeToggle
                                label="How the groups combine"
                                value={groupsMatchMode}
                                onChange={setGroupsMatchMode}
                                allLabel="Match all groups"
                                anyLabel="Match any group"
                                allDataAttr="quill-insight-filters-groups-match-all"
                                anyDataAttr="quill-insight-filters-groups-match-any"
                            />
                            {filterGroups.map((group) => (
                                <FilterGroupCard key={group.id} insightProps={insightProps} group={group} />
                            ))}
                        </div>
                        {addGroupButton && <div className="flex">{addGroupButton}</div>}
                    </>
                ) : (
                    <FilterGroupRows
                        insightProps={insightProps}
                        group={filterGroups[0]}
                        emptyText={
                            editsOneEvent
                                ? 'No filters on this event yet. Add one to narrow down this event.'
                                : 'No filters yet. Add one to narrow down the results.'
                        }
                        addFilterTrailing={addGroupButton}
                    />
                )}
                {!editsOneEvent && (
                    <>
                        <Separator />
                        <Field orientation="horizontal">
                            <Switch
                                id={testAccountsId}
                                checked={filterTestAccounts}
                                onCheckedChange={(checked) => setFilterTestAccounts(checked)}
                                disabled={!hasTestAccountFilters}
                                data-attr="quill-insight-filters-test-accounts"
                            />
                            <FieldContent>
                                <FieldLabel htmlFor={testAccountsId}>Leave out internal and test users</FieldLabel>
                                {!hasTestAccountFilters && (
                                    <FieldDescription>
                                        This project has no filters for internal and test users yet. Add them in the
                                        project settings.
                                    </FieldDescription>
                                )}
                            </FieldContent>
                        </Field>
                    </>
                )}
            </div>
        </BindLogic>
    )
}
