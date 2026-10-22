import { useActions, useValues } from 'kea'

import {
    Button,
    Dialog,
    DialogBody,
    DialogClose,
    DialogContent,
    DialogDescription,
    DialogFooter,
    DialogHeader,
    DialogTitle,
    FieldLegend,
    FieldSet,
    RadioGroup,
} from 'lib/ui/quill'

import { errorTrackingEditAccessDisabledReason } from '../../utils'
import { SuppressScopeChoice } from './SuppressScopeChoice'
import { suppressSimilarIssuesLogic } from './suppressSimilarIssuesLogic'
import { SuppressScopeKey } from './suppressSimilarScopes'

export function SuppressSimilarIssuesDialog(): JSX.Element {
    const {
        isOpen,
        snapshots,
        scopeOptions,
        selectedScope,
        selectedOption,
        scopeImpacts,
        scopeImpactsLoading,
        createdRuleLoading,
    } = useValues(suppressSimilarIssuesLogic)
    const { selectScope, createRule, dismissSuggestion } = useActions(suppressSimilarIssuesLogic)

    const multiple = snapshots.length > 1
    const titles: Record<SuppressScopeKey, string> = {
        exact: multiple ? 'These messages only' : 'This message only',
        similar: 'Similar messages',
    }

    return (
        <Dialog open={isOpen} onOpenChange={(open) => !open && dismissSuggestion()}>
            <DialogContent>
                <DialogHeader>
                    <DialogTitle>Suppress similar exceptions?</DialogTitle>
                    <DialogDescription>
                        {multiple
                            ? `These ${snapshots.length} issues are suppressed, but similar exceptions can still open new issues. Choose which ones to drop too.`
                            : 'This issue is suppressed, but similar exceptions can still open new issues. Choose which ones to drop too.'}
                    </DialogDescription>
                </DialogHeader>
                <DialogBody>
                    <FieldSet>
                        <FieldLegend variant="label">Drop new exceptions that match</FieldLegend>
                        <RadioGroup
                            value={selectedScope}
                            onValueChange={(scope) => selectScope(scope as SuppressScopeKey)}
                            className="gap-2"
                        >
                            {scopeOptions.map((option) => (
                                <SuppressScopeChoice
                                    key={option.key}
                                    option={option}
                                    title={titles[option.key]}
                                    impact={scopeImpacts?.[option.key]}
                                    impactLoading={scopeImpactsLoading}
                                />
                            ))}
                        </RadioGroup>
                    </FieldSet>
                </DialogBody>
                <DialogFooter>
                    <DialogClose
                        render={<Button variant="outline" data-attr="error-tracking-suppress-similar-dismiss" />}
                    >
                        Not now
                    </DialogClose>
                    <Button
                        variant="primary"
                        onClick={createRule}
                        loading={createdRuleLoading}
                        disabledReason={
                            errorTrackingEditAccessDisabledReason() ??
                            (selectedOption ? undefined : 'Choose which exceptions to drop')
                        }
                        data-attr="error-tracking-suppress-similar-create"
                    >
                        Suppress similar
                    </Button>
                </DialogFooter>
            </DialogContent>
        </Dialog>
    )
}
