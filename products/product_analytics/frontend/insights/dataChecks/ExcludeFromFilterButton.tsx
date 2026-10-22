import { useActions, useValues } from 'kea'

import {
    AlertDialog,
    AlertDialogClose,
    AlertDialogContent,
    AlertDialogDescription,
    AlertDialogFooter,
    AlertDialogHeader,
    AlertDialogTitle,
    AlertDialogTrigger,
    Button,
    Text,
} from '@posthog/quill'

import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { LinkPrimitive } from 'lib/lemon-ui/Link'
import { urls } from 'scenes/urls'

import { getFilterLabel } from '~/taxonomy/helpers'
import type { InsightLogicProps } from '~/types'

import type { InsightDataCheckApi } from 'products/product_analytics/frontend/generated/api.schemas'

import { insightDataChecksLogic } from './insightDataChecksLogic'

export function ExcludeFromFilterButton({
    insightProps,
    check,
    canEditFilter,
}: {
    insightProps: InsightLogicProps
    check: InsightDataCheckApi
    canEditFilter: boolean
}): JSX.Element {
    const logic = insightDataChecksLogic(insightProps)
    const { currentTeamLoading } = useValues(logic)
    const { addFilterRule, reportButtonClicked } = useActions(logic)
    const rule = check.filter_to_add

    if (!rule) {
        return (
            <Button
                variant="outline"
                size="sm"
                className="no-underline"
                render={
                    <LinkPrimitive
                        to={urls.settings('environment-customization', 'internal-user-filtering')}
                        target="_blank"
                    />
                }
                onClick={() => reportButtonClicked('edit_filter', check.key)}
                data-attr="insight-data-check-filter-settings"
            >
                Edit filter
            </Button>
        )
    }

    const property = getFilterLabel(
        rule.key,
        rule.type === 'person' ? TaxonomicFilterGroupType.PersonProperties : TaxonomicFilterGroupType.EventProperties
    )
    return (
        <AlertDialog>
            <AlertDialogTrigger
                render={
                    <Button
                        variant="outline"
                        size="sm"
                        loading={currentTeamLoading}
                        disabledReason={
                            canEditFilter
                                ? undefined
                                : 'Only project admins can change the internal and test users filter.'
                        }
                        onClick={() => reportButtonClicked('add_filter_rule', check.key)}
                        data-attr="insight-data-check-add-filter-rule"
                    />
                }
            >
                Add to project filter
            </AlertDialogTrigger>
            <AlertDialogContent>
                <AlertDialogHeader>
                    <AlertDialogTitle>Add a rule to your internal and test users filter?</AlertDialogTitle>
                    <AlertDialogDescription>
                        {`Every insight that filters out internal and test users will also leave out events where ${property} is one of these:`}
                    </AlertDialogDescription>
                </AlertDialogHeader>
                <ul className="m-0 flex max-h-48 flex-col gap-1 overflow-y-auto ps-4 text-xs">
                    {rule.value.map((value) => (
                        <li key={value}>{value}</li>
                    ))}
                </ul>
                <Text size="xs" variant="muted">
                    You can change the rule later in project settings.
                </Text>
                <AlertDialogFooter>
                    <AlertDialogClose render={<Button variant="outline" />}>Cancel</AlertDialogClose>
                    <AlertDialogClose
                        render={
                            <Button
                                variant="primary"
                                onClick={() => {
                                    reportButtonClicked('add_filter_rule_confirm', check.key)
                                    addFilterRule(check)
                                }}
                            />
                        }
                        data-attr="insight-data-check-add-filter-rule-confirm"
                    >
                        Add rule
                    </AlertDialogClose>
                </AlertDialogFooter>
            </AlertDialogContent>
        </AlertDialog>
    )
}
