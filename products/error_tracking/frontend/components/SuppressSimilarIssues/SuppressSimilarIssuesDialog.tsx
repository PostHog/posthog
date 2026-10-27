import { useActions, useValues } from 'kea'

import { IconInfo, IconLaptop } from '@posthog/icons'

import {
    Badge,
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
    Tooltip,
    TooltipContent,
    TooltipTrigger,
} from 'lib/ui/quill'

import {
    CLIENT_RULE_PUBLIC_NOTE,
    getEvalMode,
} from '../../scenes/ErrorTrackingConfigurationScene/suppression_rules/EvaluationIndicator'
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
        createdRulesLoading,
    } = useValues(suppressSimilarIssuesLogic)
    const { selectScope, createRules, dismissSuggestion } = useActions(suppressSimilarIssuesLogic)

    const multiple = snapshots.length > 1
    const runsInSdk = !!selectedOption?.rules.some((rule) => getEvalMode(rule) !== 'server')
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
                        <FieldLegend variant="label" className="flex w-full items-center justify-between gap-2">
                            <span>Drop new exceptions that match</span>
                            {runsInSdk && (
                                <span className="flex items-center gap-1">
                                    <Badge variant="success">
                                        <IconLaptop />
                                        Client
                                    </Badge>
                                    <Tooltip>
                                        <TooltipTrigger
                                            render={
                                                <Button
                                                    variant="default"
                                                    size="icon-xs"
                                                    aria-label="Who can read this rule"
                                                    data-attr="error-tracking-suppress-similar-public-note"
                                                />
                                            }
                                        >
                                            <IconInfo />
                                        </TooltipTrigger>
                                        <TooltipContent className="max-w-xs">{CLIENT_RULE_PUBLIC_NOTE}</TooltipContent>
                                    </Tooltip>
                                </span>
                            )}
                        </FieldLegend>
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
                        onClick={createRules}
                        loading={createdRulesLoading}
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
