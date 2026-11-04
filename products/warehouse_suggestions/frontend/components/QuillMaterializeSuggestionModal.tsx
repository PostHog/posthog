import { useActions, useValues } from 'kea'
import { useRef } from 'react'

import {
    Button,
    Dialog,
    DialogBody,
    DialogContent,
    DialogDescription,
    DialogFooter,
    DialogHeader,
    DialogTitle,
    FieldDescription,
    FieldGroup,
    FieldLegend,
    FieldSet,
    Item,
    ItemContent,
    ItemDescription,
} from '@posthog/quill'

import { INCREMENTAL_CHECK_LOADING } from 'scenes/data-warehouse/editor/IncrementalConfigFields'
import { QuillIncrementalConfigOptions } from 'scenes/data-warehouse/editor/QuillIncrementalConfigOptions'
import { QuillSyncFrequencySelect } from 'scenes/data-warehouse/saved_queries/QuillSyncFrequencySelect'

import { materializeScheduleNotes } from '../materializeScheduleNotes'
import {
    dataAgeLabel,
    isMaterializePayload,
    materializeSaving,
    refreshModeLabel,
    savingSentence,
    todayAgeLabel,
} from '../suggestionCopy'
import { warehouseSuggestionsLogic } from '../warehouseSuggestionsLogic'
import { QuillDataAgeMeta } from './QuillDataAgeMeta'
import { QuillSuggestionFacts } from './QuillSuggestionFacts'

export function QuillMaterializeSuggestionModal(): JSX.Element | null {
    const {
        materializeModalSuggestion,
        materializeError,
        materializeInterval,
        materializeIntervalShorterThanSuggested,
        materializeDisabledReason,
        actionsInFlight,
        refreshDraft,
        incrementalCheck,
        incrementalCheckLoading,
    } = useValues(warehouseSuggestionsLogic)
    const { confirmMaterialize, closeMaterializeModal, setMaterializeInterval, setRefreshDraft } =
        useActions(warehouseSuggestionsLogic)
    const popupRef = useRef<HTMLDivElement>(null)
    const payload = materializeModalSuggestion?.payload

    if (!materializeModalSuggestion || !payload || !isMaterializePayload(payload)) {
        return null
    }
    const inFlight = !!actionsInFlight[materializeModalSuggestion.id]
    const { pickedSeconds, suggestedHint, shorterWarning } = materializeScheduleNotes(
        payload,
        materializeInterval,
        materializeIntervalShorterThanSuggested
    )

    return (
        <Dialog open onOpenChange={(open: boolean) => !open && !inFlight && closeMaterializeModal()}>
            <DialogContent
                ref={popupRef}
                initialFocus={popupRef}
                size="wide"
                className="max-w-xl"
                showCloseButton={!inFlight}
            >
                <DialogHeader>
                    <DialogTitle>{`Materialize ${payload.subject_name}`}</DialogTitle>
                    <DialogDescription>
                        Stores the result and refreshes it on a schedule. Reads of this view use the stored rows.
                    </DialogDescription>
                </DialogHeader>
                <DialogBody>
                    <FieldGroup>
                        <div className="flex flex-col gap-1">
                            <QuillSyncFrequencySelect
                                value={materializeInterval}
                                onChange={setMaterializeInterval}
                                loading={inFlight}
                            />
                            {suggestedHint && <FieldDescription>{suggestedHint}</FieldDescription>}
                        </div>
                        <FieldSet disabled={inFlight}>
                            <FieldLegend variant="label">Refresh mode</FieldLegend>
                            <QuillIncrementalConfigOptions
                                check={incrementalCheckLoading ? INCREMENTAL_CHECK_LOADING : incrementalCheck}
                                draft={refreshDraft}
                                onChange={setRefreshDraft}
                            />
                        </FieldSet>
                        <QuillSuggestionFacts
                            facts={[
                                {
                                    label: 'With these settings',
                                    value: <QuillDataAgeMeta age={dataAgeLabel(payload, pickedSeconds)} />,
                                    details: [
                                        todayAgeLabel(payload),
                                        refreshModeLabel(refreshDraft.enabled, refreshDraft.incrementalKey),
                                    ],
                                },
                                {
                                    label: 'Estimated at the suggested settings',
                                    value: savingSentence(materializeSaving(payload)),
                                },
                            ]}
                        />
                        {shorterWarning && (
                            <Item variant="outline" size="sm" tone="warning">
                                <ItemContent>
                                    <ItemDescription>{shorterWarning}</ItemDescription>
                                </ItemContent>
                            </Item>
                        )}
                        {materializeError && (
                            <Item variant="outline" size="sm" tone="destructive" role="alert">
                                <ItemContent>
                                    <ItemDescription>{materializeError}</ItemDescription>
                                </ItemContent>
                            </Item>
                        )}
                    </FieldGroup>
                </DialogBody>
                <DialogFooter>
                    <Button
                        variant="outline"
                        onClick={closeMaterializeModal}
                        disabledReason={inFlight ? 'Working' : undefined}
                    >
                        Cancel
                    </Button>
                    <Button
                        variant="primary"
                        loading={inFlight}
                        disabledReason={materializeDisabledReason ?? undefined}
                        onClick={() => confirmMaterialize()}
                        data-attr="warehouse-suggestions-materialize-confirm"
                    >
                        Materialize
                    </Button>
                </DialogFooter>
            </DialogContent>
        </Dialog>
    )
}
