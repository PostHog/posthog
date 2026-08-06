import { useActions, useValues } from 'kea'

import { IconPlus } from '@posthog/icons'

import { TaxonomicFilterHeadless } from 'lib/components/TaxonomicFilter/headless'
import { TaxonomicFilterMenu } from 'lib/components/TaxonomicFilter/menu/TaxonomicFilterMenu'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { Button } from 'lib/ui/quill'

import { BreakdownsTileButton } from './BreakdownsTileButton'
import { miniBreakdownsLogic } from './miniBreakdownsLogic'

export function MiniBreakdowns(): JSX.Element {
    const { breakdownProperties, propertyPickerOpenRequest } = useValues(miniBreakdownsLogic)
    const { addBreakdownProperty, removeBreakdownProperty, openPropertyPicker } = useActions(miniBreakdownsLogic)

    return (
        <div className="flex h-full min-h-0 flex-col">
            <div className="flex shrink-0 justify-end px-3 pb-1 pt-2">
                <TaxonomicFilterHeadless.Root
                    className="contents"
                    bindRootProps={false}
                    groupType={TaxonomicFilterGroupType.EventProperties}
                    taxonomicGroupTypes={[TaxonomicFilterGroupType.EventProperties]}
                    eventNames={['$exception']}
                    excludedProperties={{
                        [TaxonomicFilterGroupType.EventProperties]: breakdownProperties.map(({ property }) => property),
                    }}
                    onChange={(_, value) => {
                        if (value) {
                            addBreakdownProperty(String(value))
                        }
                    }}
                >
                    <TaxonomicFilterMenu
                        key={propertyPickerOpenRequest}
                        defaultOpen={propertyPickerOpenRequest > 0}
                        defaultOpenState="combobox"
                        trigger={({ open }) => (
                            <Button
                                variant="outline"
                                size="xs"
                                aria-expanded={open}
                                onClick={() => {
                                    if (!open) {
                                        openPropertyPicker()
                                    }
                                }}
                            >
                                <IconPlus />
                                Add property
                            </Button>
                        )}
                    />
                </TaxonomicFilterHeadless.Root>
            </div>
            <div className="min-h-0 flex-1 overflow-y-auto px-3 pb-2">
                <div className="overflow-hidden rounded bg-surface-primary">
                    {breakdownProperties.map((item) => (
                        <BreakdownsTileButton
                            key={item.property}
                            item={item}
                            onRemove={item.removable ? () => removeBreakdownProperty(item.property) : undefined}
                        />
                    ))}
                </div>
            </div>
        </div>
    )
}
