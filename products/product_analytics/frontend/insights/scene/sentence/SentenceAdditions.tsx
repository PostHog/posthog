import { useActions, useValues } from 'kea'

import { IconPlus } from '@posthog/icons'
import { Button, DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuTrigger } from '@posthog/quill'

import type { InsightLogicProps } from '~/types'

import { FiltersPopover } from './filters/FiltersPopover'
import { insightSentenceLogic } from './insightSentenceLogic'
import { SplitPickerPopover } from './SplitPickerPopover'

/** The parts of the sentence that are not set yet, apart from another event. The caller lays the buttons out. */
export function SentenceAdditions({ insightProps }: { insightProps: InsightLogicProps }): JSX.Element | null {
    const { sentenceInput, formulaPending } = useValues(insightSentenceLogic(insightProps))
    const { toggleCompare, setFormulaPending } = useActions(insightSentenceLogic(insightProps))

    if (!sentenceInput) {
        return null
    }

    const canAddFormula = !sentenceInput.formulas.length && !formulaPending
    const canAddCompare = !sentenceInput.comparing

    return (
        <>
            {!sentenceInput.splits.length && (
                <SplitPickerPopover
                    insightProps={insightProps}
                    trigger={(open, toggle) => (
                        <Button
                            variant="outline"
                            size="sm"
                            aria-expanded={open}
                            onClick={toggle}
                            data-attr="quill-insight-add-split"
                        >
                            <IconPlus />
                            split by
                        </Button>
                    )}
                />
            )}
            {!sentenceInput.filterCount && (
                <FiltersPopover
                    insightProps={insightProps}
                    trigger={(open, toggle) => (
                        <Button
                            variant="outline"
                            size="sm"
                            aria-expanded={open}
                            onClick={toggle}
                            data-attr="quill-insight-add-filters"
                        >
                            <IconPlus />
                            with filters
                        </Button>
                    )}
                />
            )}
            {/* The two least used additions share one button while both are unset, so the row stays short. */}
            {canAddFormula && canAddCompare ? (
                <DropdownMenu>
                    <DropdownMenuTrigger
                        render={<Button variant="outline" size="sm" data-attr="quill-insight-add-more" />}
                    >
                        <IconPlus />
                        more
                    </DropdownMenuTrigger>
                    <DropdownMenuContent align="start" className="min-w-56">
                        <DropdownMenuItem onClick={() => setFormulaPending(true)} data-attr="quill-insight-add-formula">
                            Combine the events with a formula
                        </DropdownMenuItem>
                        <DropdownMenuItem onClick={() => toggleCompare()} data-attr="quill-insight-add-compare">
                            Compare to the previous period
                        </DropdownMenuItem>
                    </DropdownMenuContent>
                </DropdownMenu>
            ) : (
                <>
                    {canAddFormula && (
                        <Button
                            variant="outline"
                            size="sm"
                            onClick={() => setFormulaPending(true)}
                            data-attr="quill-insight-add-formula"
                        >
                            <IconPlus />
                            combined with a formula
                        </Button>
                    )}
                    {canAddCompare && (
                        <Button
                            variant="outline"
                            size="sm"
                            onClick={() => toggleCompare()}
                            data-attr="quill-insight-add-compare"
                        >
                            <IconPlus />
                            compared to the previous period
                        </Button>
                    )}
                </>
            )}
        </>
    )
}
