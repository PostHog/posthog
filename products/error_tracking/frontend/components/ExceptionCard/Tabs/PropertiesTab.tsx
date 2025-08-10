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
import { ContextDisplay } from '../../ContextDisplay'

export interface PropertiesTabProps extends TabsPrimitiveContentProps {}

export function PropertiesTab({ ...props }: PropertiesTabProps): JSX.Element {
    const { properties, exceptionAttributes, additionalProperties } = useValues(errorPropertiesLogic)
    const { loading, showJSONProperties, showAdditionalProperties } = useValues(exceptionCardLogic)

    return (
        <TabsPrimitiveContent {...props}>
            <div className="flex justify-end items-center border-b-1 bg-surface-secondary">
                <ShowDropDownMenu />
            </div>
            <div>
                {showJSONProperties ? (
                    <JSONViewer src={properties} name="event" collapsed={1} collapseStringsAfterLength={80} sortKeys />
                ) : (
                    <ContextDisplay
                        loading={loading}
                        exceptionAttributes={exceptionAttributes}
                        additionalProperties={showAdditionalProperties ? additionalProperties : {}}
                    />
                )}
            </div>
        </TabsPrimitiveContent>
    )
}

function ShowDropDownMenu(): JSX.Element {
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
