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
    Skeleton,
    Tooltip,
    TooltipContent,
    TooltipTrigger,
} from 'lib/ui/quill'
import { pluralize } from 'lib/utils/strings'

import {
    CLIENT_RULE_PUBLIC_NOTE,
    getEvalMode,
} from '../../scenes/ErrorTrackingConfigurationScene/suppression_rules/EvaluationIndicator'
import { errorTrackingEditAccessDisabledReason } from '../../utils'
import { MessagePattern } from './MessagePattern'
import { SuppressScopeChoice } from './SuppressScopeChoice'
import { suppressSimilarIssuesLogic } from './suppressSimilarIssuesLogic'
import { SuppressScopeKey } from './suppressSimilarScopes'

export function SuppressSimilarIssuesDialog(): JSX.Element {
    const {
        isOpen,
        snapshots,
        snapshotsLoading,
        scopeOptions,
        selectedScope,
        selectedOption,
        selectedImpact,
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
                    <DialogTitle>Suppress future exceptions?</DialogTitle>
                    <DialogDescription>
                        {multiple
                            ? `These ${snapshots.length} issues are suppressed. You can also drop new exceptions with matching messages.`
                            : 'This issue is suppressed. You can also drop new exceptions with a matching message.'}
                    </DialogDescription>
                </DialogHeader>
                <DialogBody>
                    {snapshotsLoading ? (
                        <div role="status" aria-label="Loading exception messages" className="flex flex-col gap-3">
                            <Skeleton className="h-5 w-48" />
                            <Skeleton className="h-10 w-full" />
                        </div>
                    ) : (
                        <FieldSet>
                            <FieldLegend variant="label" className="flex w-full items-center justify-between gap-2">
                                <span>Messages to drop</span>
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
                                            <TooltipContent className="max-w-xs">
                                                {CLIENT_RULE_PUBLIC_NOTE}
                                            </TooltipContent>
                                        </Tooltip>
                                    </span>
                                )}
                            </FieldLegend>
                            {scopeOptions.length > 1 ? (
                                <RadioGroup
                                    value={selectedScope}
                                    onValueChange={(scope) => selectScope(scope as SuppressScopeKey)}
                                    className="gap-2"
                                    aria-label="Messages to drop"
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
                            ) : (
                                <>
                                    <div className="flex flex-wrap gap-1">
                                        {selectedOption?.messages.map((segments, index) => (
                                            <MessagePattern key={index} segments={segments} />
                                        ))}
                                    </div>
                                    {scopeImpactsLoading ? (
                                        <Skeleton className="h-4 w-44" />
                                    ) : (
                                        <p className="m-0 text-sm text-secondary">
                                            {selectedImpact
                                                ? `${pluralize(selectedImpact.exceptions, 'exception')} across ${pluralize(selectedImpact.issueCount, 'issue')} in the last 7 days`
                                                : "Couldn't count matching exceptions"}
                                        </p>
                                    )}
                                </>
                            )}
                        </FieldSet>
                    )}
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
                            (selectedOption ? undefined : 'Loading exception messages')
                        }
                        data-attr="error-tracking-suppress-similar-create"
                    >
                        Create rule
                    </Button>
                </DialogFooter>
            </DialogContent>
        </Dialog>
    )
}
