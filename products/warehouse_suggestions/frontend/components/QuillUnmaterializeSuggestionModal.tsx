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
    Text,
} from '@posthog/quill'

import {
    isUnmaterializePayload,
    monthlyCost,
    readTimeLabel,
    savingSentence,
    unmaterializeSaving,
} from '../suggestionCopy'
import { warehouseSuggestionsLogic } from '../warehouseSuggestionsLogic'
import { QuillSuggestionFacts } from './QuillSuggestionFacts'

export function QuillUnmaterializeSuggestionModal(): JSX.Element | null {
    const { acceptConfirmSuggestion, actionsInFlight } = useValues(warehouseSuggestionsLogic)
    const { confirmAccept, closeAcceptConfirm } = useActions(warehouseSuggestionsLogic)
    const payload = acceptConfirmSuggestion?.payload

    if (!acceptConfirmSuggestion || !payload || !isUnmaterializePayload(payload)) {
        return null
    }
    const inFlight = !!actionsInFlight[acceptConfirmSuggestion.id]

    return (
        <Dialog open onOpenChange={(open: boolean) => !open && !inFlight && closeAcceptConfirm()}>
            <DialogContent size="wide" className="max-w-xl" showCloseButton={!inFlight}>
                <DialogHeader>
                    <DialogTitle>{`Stop materializing ${payload.subject_name}?`}</DialogTitle>
                    <DialogDescription>
                        Deletes its stored table and stops its refreshes. Each read computes the view from its query
                        instead. You can materialize it again later.
                    </DialogDescription>
                </DialogHeader>
                <DialogBody>
                    <QuillSuggestionFacts
                        facts={[
                            {
                                label: 'Materialized now',
                                value: monthlyCost({
                                    seconds: payload.refresh_seconds_per_month,
                                    bytes: payload.refresh_bytes_per_month,
                                }),
                            },
                            {
                                label: 'Computed on each read',
                                value: `${monthlyCost({ seconds: payload.live_seconds_per_month, bytes: payload.live_bytes_per_month })} (estimate)`,
                                details: [readTimeLabel(payload.read_seconds)],
                            },
                        ]}
                        footer={
                            <Text size="sm" weight="semibold" className="m-0 text-success-foreground">
                                {savingSentence(unmaterializeSaving(payload))}
                            </Text>
                        }
                    />
                </DialogBody>
                <DialogFooter>
                    <Button
                        variant="outline"
                        onClick={closeAcceptConfirm}
                        disabledReason={inFlight ? 'Working' : undefined}
                    >
                        Cancel
                    </Button>
                    <Button
                        variant="primary"
                        loading={inFlight}
                        onClick={() => confirmAccept()}
                        data-attr="warehouse-suggestions-unmaterialize-confirm"
                    >
                        Stop materializing
                    </Button>
                </DialogFooter>
            </DialogContent>
        </Dialog>
    )
}
