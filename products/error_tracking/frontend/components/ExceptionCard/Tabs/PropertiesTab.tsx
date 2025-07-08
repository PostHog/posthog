import { errorPropertiesLogic } from 'lib/components/Errors/errorPropertiesLogic'
import { JSONViewer } from 'lib/components/JSONViewer'
import { TabsPrimitiveContent, TabsPrimitiveContentProps } from 'lib/ui/TabsPrimitive/TabsPrimitive'
import { useActions, useValues } from 'kea'

import { LemonButton } from '@posthog/lemon-ui'
import { exceptionCardLogic } from '../exceptionCardLogic'
import {
    DropdownMenu,
    DropdownMenuCheckboxItem,
    DropdownMenuContent,
    DropdownMenuItemIndicator,
    DropdownMenuTrigger,
} from 'lib/ui/DropdownMenu/DropdownMenu'
import { ButtonPrimitive } from 'lib/ui/Button/ButtonPrimitives'
import { IconChevronDown } from '@posthog/icons'
import { ContextLoader, ContextTable } from '../../ContextDisplay'
import { identifierToHuman } from 'lib/utils'
import { concatValues } from 'lib/components/Errors/utils'

export interface PropertiesTabProps extends TabsPrimitiveContentProps {}

export function PropertiesTab({ ...props }: PropertiesTabProps): JSX.Element {
    const { properties, exceptionAttributes, additionalProperties } = useValues(errorPropertiesLogic)
    const { loading, showJSONProperties, showAdditionalProperties } = useValues(exceptionCardLogic)

    const additionalEntries = Object.entries(additionalProperties).map(
        ([key, value]) => [identifierToHuman(key, 'title'), value] as [string, unknown]
    )
    const exceptionEntries: [string, unknown][] = exceptionAttributes
        ? [
              ['Level', exceptionAttributes.level],
              ['Synthetic', exceptionAttributes.synthetic],
              ['Library', concatValues(exceptionAttributes, 'lib', 'libVersion')],
              ['Handled', exceptionAttributes.handled],
              ['Browser', concatValues(exceptionAttributes, 'browser', 'browserVersion')],
              ['OS', concatValues(exceptionAttributes, 'os', 'osVersion')],
              ['URL', exceptionAttributes.url],
          ]
        : []

    return (
        <TabsPrimitiveContent {...props}>
            <div className="flex justify-end items-center border-b-1 bg-surface-secondary">
                <ShowDropDownMenu hasAdditionalEntries={additionalEntries.length > 0} />
            </div>
            <div>
                {showJSONProperties ? (
                    <JSONViewer src={properties} name="event" collapsed={1} collapseStringsAfterLength={80} sortKeys />
                ) : (
                    <ContextLoader loading={loading}>
                        <ContextTable
                            entries={[...exceptionEntries, ...(showAdditionalProperties ? additionalEntries : [])]}
                        />
                    </ContextLoader>
                )}
            </div>
        </TabsPrimitiveContent>
    )
}

function ShowDropDownMenu({ hasAdditionalEntries }: { hasAdditionalEntries: boolean }): JSX.Element {
    const { showJSONProperties, showAdditionalProperties } = useValues(exceptionCardLogic)
    const { setShowJSONProperties, setShowAdditionalProperties } = useActions(exceptionCardLogic)

    return (
        <DropdownMenu>
            <DropdownMenuTrigger asChild>
                <LemonButton size="small" sideIcon={<IconChevronDown />}>
                    Show
                </LemonButton>
            </DropdownMenuTrigger>
            <DropdownMenuContent>
                {hasAdditionalEntries && (
                    <DropdownMenuCheckboxItem
                        checked={showAdditionalProperties}
                        onCheckedChange={setShowAdditionalProperties}
                        asChild
                    >
                        <ButtonPrimitive menuItem size="sm">
                            <DropdownMenuItemIndicator intent="checkbox" />
                            Additional properties
                        </ButtonPrimitive>
                    </DropdownMenuCheckboxItem>
                )}
                <DropdownMenuCheckboxItem checked={showJSONProperties} onCheckedChange={setShowJSONProperties} asChild>
                    <ButtonPrimitive menuItem size="sm">
                        <DropdownMenuItemIndicator intent="checkbox" />
                        As JSON
                    </ButtonPrimitive>
                </DropdownMenuCheckboxItem>
            </DropdownMenuContent>
        </DropdownMenu>
    )
}
