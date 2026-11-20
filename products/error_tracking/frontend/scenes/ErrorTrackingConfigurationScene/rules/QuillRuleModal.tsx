import { useActions, useValues } from 'kea'
import { ReactNode } from 'react'

import { IconFlask } from '@posthog/icons'
import {
    Button,
    Dialog,
    DialogBody,
    DialogContent,
    DialogDescription,
    DialogFooter,
    DialogHeader,
    DialogTitle,
    Item,
    ItemContent,
    Text,
    ToggleGroup,
    ToggleGroupItem,
} from '@posthog/quill'

import { PropertyFilters } from 'lib/components/PropertyFilters/PropertyFilters'
import { closesIntoLemonPopover } from 'lib/components/QuillSurface/closesIntoLemonPopover'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { QuillSurfaceContext } from 'lib/ui/QuillSurface/quillSurfaceContext'

import { AnyPropertyFilter, FilterLogicalOperator } from '~/types'

import { DisabledRuleBanner } from './DisabledRuleBanner'
import { MatchResultBanner } from './MatchResultBanner'

const MATCH_OPTIONS = [
    { label: 'All', value: FilterLogicalOperator.And },
    { label: 'Any', value: FilterLogicalOperator.Or },
]

export interface QuillRuleModalProps {
    logic: any
    ruleLabel: string
    description: string
    pageKey: string
    width: number
    taxonomicGroupTypes: TaxonomicFilterGroupType[]
    saveDisabledReason?: string
    suffix?: (issuesLink: JSX.Element, dateRangeLabel: string) => JSX.Element
    filterLabels?: ReactNode
    extraFields?: ReactNode
    footerExtra?: ReactNode
    samplingRate?: number
    filtersOptional: boolean
    showTestButton: boolean
    deleteLabel: string
    deleteDisabledReason?: string
    onDeleteClick: () => void
}

export function QuillRuleModal({
    logic,
    ruleLabel,
    description,
    pageKey,
    width,
    taxonomicGroupTypes,
    saveDisabledReason,
    suffix,
    filterLabels,
    extraFields,
    footerExtra,
    samplingRate,
    filtersOptional,
    showTestButton,
    deleteLabel,
    deleteDisabledReason,
    onDeleteClick,
}: QuillRuleModalProps): JSX.Element {
    const { isOpen, rule, hasFilters, matchResult, matchResultLoading, savingLoading, deletingLoading, dateRange } =
        useValues(logic)
    const { closeModal, updateRule, loadMatchCount, saveRule, increaseDateRange } = useActions(logic)

    const isEditing = rule.id !== 'new'

    return (
        <Dialog
            open={isOpen}
            // PropertyFilters opens Lemon popovers that portal outside the dialog. A modal dialog would make them
            // inert and pull focus back, so the dialog stays non-modal and ignores clicks that land in them.
            modal={false}
            onOpenChange={(open, details) => {
                if (closesIntoLemonPopover(open, details)) {
                    details.cancel()
                    return
                }
                if (!open) {
                    closeModal()
                }
            }}
        >
            <DialogContent size="wide" className={width >= 800 ? 'max-w-200' : 'max-w-175'}>
                <DialogHeader>
                    <DialogTitle>{isEditing ? `Edit ${ruleLabel} rule` : `New ${ruleLabel} rule`}</DialogTitle>
                    <DialogDescription>{description}</DialogDescription>
                </DialogHeader>
                <DialogBody>
                    <div className="flex flex-col gap-4">
                        {rule.disabled_data && <DisabledRuleBanner rule={rule} onClose={closeModal} />}
                        <div className="flex flex-col gap-3">
                            <div className="flex flex-wrap items-center justify-between gap-2">
                                <div className="flex flex-wrap items-center gap-3">
                                    <Text size="sm" weight="semibold" render={<span className="m-0" />}>
                                        Filters
                                    </Text>
                                    {filterLabels && (
                                        <>
                                            <span className="text-muted-foreground">·</span>
                                            {filterLabels}
                                        </>
                                    )}
                                </div>
                                <div className="flex items-center gap-2">
                                    <Text size="sm" variant="muted" render={<span className="m-0" />}>
                                        Match
                                    </Text>
                                    <ToggleGroup
                                        variant="outline"
                                        size="sm"
                                        aria-label="Match"
                                        value={[rule.filters.type]}
                                        onValueChange={(next: string[]) => {
                                            const type = next[0] as FilterLogicalOperator | undefined
                                            if (type) {
                                                updateRule({ ...rule, filters: { ...rule.filters, type } })
                                            }
                                        }}
                                    >
                                        {MATCH_OPTIONS.map((option) => (
                                            <ToggleGroupItem key={option.value} value={option.value}>
                                                {option.label}
                                            </ToggleGroupItem>
                                        ))}
                                    </ToggleGroup>
                                </div>
                            </div>
                            <QuillSurfaceContext.Provider value={true}>
                                <PropertyFilters
                                    editable
                                    propertyFilters={(rule.filters.values as AnyPropertyFilter[]) ?? []}
                                    taxonomicGroupTypes={taxonomicGroupTypes}
                                    onChange={(properties: AnyPropertyFilter[]) =>
                                        updateRule({
                                            ...rule,
                                            filters: { ...rule.filters, values: properties },
                                        })
                                    }
                                    pageKey={pageKey}
                                    buttonSize="small"
                                    propertyGroupType={rule.filters.type}
                                    hasRowOperator={false}
                                    disablePopover
                                />
                            </QuillSurfaceContext.Provider>
                        </div>

                        {extraFields}

                        {matchResult !== null && !matchResultLoading && suffix ? (
                            <Item tone={matchResult.exceptionCount === 0 ? 'destructive' : 'success'} size="sm">
                                <ItemContent>
                                    <Text size="xs" render={<div className="m-0" />}>
                                        <MatchResultBanner
                                            matchResult={matchResult}
                                            properties={(rule.filters.values as AnyPropertyFilter[]) ?? []}
                                            filterType={rule.filters.type}
                                            dateRange={dateRange}
                                            onIncreaseDateRange={increaseDateRange}
                                            suffix={suffix}
                                            samplingRate={samplingRate}
                                        />
                                    </Text>
                                </ItemContent>
                            </Item>
                        ) : null}
                    </div>
                </DialogBody>
                <DialogFooter className="flex-wrap sm:justify-between">
                    <div className="flex flex-wrap gap-2">
                        {isEditing && (
                            <Button
                                variant="destructive-outline"
                                loading={deletingLoading}
                                disabledReason={deleteDisabledReason}
                                onClick={onDeleteClick}
                            >
                                {deleteLabel}
                            </Button>
                        )}
                        {footerExtra}
                    </div>
                    <div className="flex flex-wrap gap-2">
                        {showTestButton && (
                            <Button
                                variant="outline"
                                loading={matchResultLoading}
                                disabledReason={
                                    !filtersOptional && !hasFilters ? 'Add at least one filter first' : undefined
                                }
                                onClick={() => loadMatchCount()}
                            >
                                <IconFlask />
                                Test rule
                            </Button>
                        )}
                        <Button variant="outline" onClick={closeModal}>
                            Cancel
                        </Button>
                        <Button
                            variant="primary"
                            disabledReason={saveDisabledReason}
                            onClick={() => saveRule()}
                            loading={savingLoading}
                        >
                            Save
                        </Button>
                    </div>
                </DialogFooter>
            </DialogContent>
        </Dialog>
    )
}
