import { IconEllipsis, IconX } from '@posthog/icons'
import { Button, ButtonGroup, Popover, PopoverContent, PopoverTrigger } from '@posthog/quill'

import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'

import { BreakdownType } from '~/types'

import { BreakdownTagLabel } from './BreakdownTagLabel'
import { QuillBreakdownTagMenu } from './QuillBreakdownTagMenu'
import { TaxonomicBreakdownPopover } from './TaxonomicBreakdownPopover'
import { useBreakdownPropertyName } from './useBreakdownPropertyName'

export interface QuillEditableBreakdownTagProps {
    breakdown: string | number
    breakdownType: BreakdownType
    taxonomicBreakdownType: TaxonomicFilterGroupType | undefined
    hasMenu: boolean
    filterOpen: boolean
    setFilterOpen: (open: boolean) => void
    menuOpen: boolean
    setMenuOpen: (open: boolean) => void
    onRemove: () => void
    disablePropertyInfo?: boolean
}

export function QuillEditableBreakdownTag({
    breakdown,
    breakdownType,
    taxonomicBreakdownType,
    hasMenu,
    filterOpen,
    setFilterOpen,
    menuOpen,
    setMenuOpen,
    onRemove,
    disablePropertyInfo,
}: QuillEditableBreakdownTagProps): JSX.Element {
    const propertyName = useBreakdownPropertyName(breakdown, breakdownType)

    return (
        <ButtonGroup className="max-w-full min-w-0" data-attr="breakdown-tag">
            <TaxonomicBreakdownPopover
                open={filterOpen}
                setOpen={setFilterOpen}
                breakdownValue={breakdown}
                breakdownType={breakdownType}
                taxonomicType={taxonomicBreakdownType}
            >
                <Button variant="outline" className="min-w-0 shrink" title={String(propertyName)}>
                    <span className="min-w-0 truncate">
                        <BreakdownTagLabel
                            propertyName={propertyName}
                            breakdownType={breakdownType}
                            disablePropertyInfo={disablePropertyInfo || filterOpen || menuOpen}
                        />
                    </span>
                </Button>
            </TaxonomicBreakdownPopover>
            {hasMenu ? (
                <Popover open={menuOpen} onOpenChange={setMenuOpen}>
                    <PopoverTrigger
                        render={
                            <Button
                                variant="outline"
                                size="icon"
                                aria-label="Breakdown options"
                                tooltip="Breakdown options"
                                data-attr="breakdown-tag-options"
                            />
                        }
                    >
                        <IconEllipsis />
                    </PopoverTrigger>
                    <PopoverContent align="start" className="w-72 gap-2">
                        <QuillBreakdownTagMenu />
                    </PopoverContent>
                </Popover>
            ) : (
                <Button
                    variant="outline"
                    size="icon"
                    aria-label="Remove breakdown"
                    tooltip="Remove breakdown"
                    onClick={onRemove}
                    data-attr="breakdown-tag-close"
                >
                    <IconX />
                </Button>
            )}
        </ButtonGroup>
    )
}
