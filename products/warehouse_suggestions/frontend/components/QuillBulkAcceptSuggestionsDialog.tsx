import { useActions, useValues } from 'kea'

import {
    Button,
    Dialog,
    DialogBody,
    DialogContent,
    DialogDescription,
    DialogFooter,
    DialogHeader,
    DialogTitle,
    FieldGroup,
} from '@posthog/quill'

import { QuillSyncFrequencySelect } from 'scenes/data-warehouse/saved_queries/QuillSyncFrequencySelect'

import { countOf, isDeprecatePayload, isMaterializePayload, suggestionCountsText } from '../suggestionCopy'
import { catalogEditBlockedReason } from '../warehouseSuggestionsLogic'
import { BulkIntervalChoice, warehouseSuggestionsSectionLogic } from '../warehouseSuggestionsSectionLogic'
import { ActionChoice, RefreshChoice } from './DeprecateSuggestionModal'
import { QuillChoice, QuillChoiceGroup } from './QuillChoiceGroup'

const INTERVAL_CHOICES: QuillChoice<BulkIntervalChoice>[] = [
    {
        value: 'suggested',
        label: "Each view's suggested interval",
        description: 'Each view refreshes on the schedule suggested for it.',
        'data-attr': 'warehouse-suggestions-bulk-interval-suggested',
    },
    {
        value: 'fixed',
        label: 'One interval for all',
        description: 'Every view refreshes on the interval you pick.',
        'data-attr': 'warehouse-suggestions-bulk-interval-fixed',
    },
]

const ACTION_CHOICES: QuillChoice<ActionChoice>[] = [
    {
        value: 'deprecate',
        label: 'Mark them deprecated',
        description: 'They stay in the data catalog with a deprecated label, so people know not to use them.',
        'data-attr': 'warehouse-suggestions-bulk-deprecate-mark',
    },
    {
        value: 'delete',
        label: 'Delete them',
        description: "Deletes the views and their stored tables. You can't undo this.",
        'data-attr': 'warehouse-suggestions-bulk-deprecate-delete',
    },
]

const REFRESH_CHOICES: QuillChoice<RefreshChoice>[] = [
    {
        value: 'stop',
        label: 'Stop refreshing them',
        description:
            'Deletes their stored tables and stops their refreshes. PostHog keeps a refresh when another view or a sync reads that view. You can materialize them again later.',
        'data-attr': 'warehouse-suggestions-bulk-deprecate-stop-refreshing',
    },
    {
        value: 'keep',
        label: 'Keep refreshing them',
        description: 'They stay materialized, and their refreshes keep their cost.',
        'data-attr': 'warehouse-suggestions-bulk-deprecate-keep-refreshing',
    },
]

export function QuillBulkAcceptSuggestionsDialog(): JSX.Element {
    const {
        bulkAcceptOpen,
        selectedSuggestions,
        selectedViewDeprecations,
        acceptChoices,
        deleteViewsBlockedReason,
        bulkAcceptBlockedReason,
    } = useValues(warehouseSuggestionsSectionLogic)
    const { closeBulkAccept, setAcceptChoices, confirmBulkAccept } = useActions(warehouseSuggestionsSectionLogic)
    const materializes = selectedSuggestions.some((suggestion) => isMaterializePayload(suggestion.payload))
    const refreshesViews = selectedViewDeprecations.some(
        ({ payload }) => isDeprecatePayload(payload) && payload.materialized !== false
    )
    const actionChoices = ACTION_CHOICES.map((choice) => ({
        ...choice,
        disabledReason: choice.value === 'delete' ? deleteViewsBlockedReason : catalogEditBlockedReason(),
    }))
    const count = countOf(selectedSuggestions.length, 'suggestion', 'suggestions')

    return (
        <Dialog open={bulkAcceptOpen} onOpenChange={(open: boolean) => !open && closeBulkAccept()}>
            <DialogContent size="wide" className="max-w-xl" data-attr="warehouse-suggestions-bulk-accept-dialog">
                <DialogHeader>
                    <DialogTitle>{`Approve ${count}?`}</DialogTitle>
                    <DialogDescription>{suggestionCountsText(selectedSuggestions)}</DialogDescription>
                </DialogHeader>
                <DialogBody>
                    <FieldGroup>
                        {materializes && (
                            <div className="flex flex-col gap-2">
                                <QuillChoiceGroup<BulkIntervalChoice>
                                    legend="How often views refresh"
                                    idPrefix="bulk-accept-interval"
                                    value={acceptChoices.intervalChoice}
                                    onChange={(intervalChoice) => setAcceptChoices({ intervalChoice })}
                                    choices={INTERVAL_CHOICES}
                                    disabled={false}
                                />
                                {acceptChoices.intervalChoice === 'fixed' && (
                                    <QuillSyncFrequencySelect
                                        value={acceptChoices.interval}
                                        onChange={(interval) => setAcceptChoices({ interval })}
                                    />
                                )}
                            </div>
                        )}
                        {selectedViewDeprecations.length > 0 && (
                            <QuillChoiceGroup<ActionChoice>
                                legend="Unused views"
                                idPrefix="bulk-accept-deprecate"
                                value={acceptChoices.deleteViews ? 'delete' : 'deprecate'}
                                onChange={(choice) => setAcceptChoices({ deleteViews: choice === 'delete' })}
                                choices={actionChoices}
                                disabled={false}
                            />
                        )}
                        {refreshesViews && !acceptChoices.deleteViews && (
                            <QuillChoiceGroup<RefreshChoice>
                                legend="Their materialization"
                                idPrefix="bulk-accept-refresh"
                                value={acceptChoices.keepMaterialized ? 'keep' : 'stop'}
                                onChange={(choice) => setAcceptChoices({ keepMaterialized: choice === 'keep' })}
                                choices={REFRESH_CHOICES}
                                disabled={false}
                            />
                        )}
                    </FieldGroup>
                </DialogBody>
                <DialogFooter>
                    <Button variant="outline" onClick={closeBulkAccept}>
                        Cancel
                    </Button>
                    <Button
                        variant={
                            acceptChoices.deleteViews && selectedViewDeprecations.length > 0
                                ? 'destructive-outline'
                                : 'primary'
                        }
                        disabledReason={bulkAcceptBlockedReason}
                        onClick={() => confirmBulkAccept()}
                        data-attr="warehouse-suggestions-bulk-accept-confirm"
                    >
                        {`Approve ${count}`}
                    </Button>
                </DialogFooter>
            </DialogContent>
        </Dialog>
    )
}
