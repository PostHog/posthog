import { useActions, useValues } from 'kea'

import { IconChevronDown } from '@posthog/icons'

import { errorPropertiesLogic } from 'lib/components/Errors/errorPropertiesLogic'
import { JSONViewer } from 'lib/components/JSONViewer'
import { ButtonPrimitive } from 'lib/ui/Button/ButtonPrimitives'
import {
    DropdownMenu,
    DropdownMenuCheckboxItem,
    DropdownMenuContent,
    DropdownMenuGroup,
    DropdownMenuItemIndicator,
    DropdownMenuTrigger,
} from 'lib/ui/DropdownMenu/DropdownMenu'
import { TabsPrimitiveContent, TabsPrimitiveContentProps } from 'lib/ui/TabsPrimitive/TabsPrimitive'

import { ContextDisplay } from '../../ContextDisplay/ContextDisplay'
import { exceptionCardLogic } from '../exceptionCardLogic'
import { SubHeader } from './SubHeader'

export interface PropertiesTabProps extends TabsPrimitiveContentProps {}

export function PropertiesTab({ ...props }: PropertiesTabProps): JSX.Element {
    const { properties, exceptionAttributes, additionalProperties } = useValues(errorPropertiesLogic)
    const { loading, showJSONProperties, showAdditionalProperties } = useValues(exceptionCardLogic)

    return (
        <TabsPrimitiveContent {...props}>
            <SubHeader className="justify-end">
                <ShowDropDownMenu />
            </SubHeader>
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
                <ButtonPrimitive size="sm" className="h-[1.4rem] px-2">
                    Show
                    <IconChevronDown />
                </ButtonPrimitive>
            </DropdownMenuTrigger>
            <DropdownMenuContent>
                <DropdownMenuGroup>
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
                    <DropdownMenuCheckboxItem
                        checked={showJSONProperties}
                        onCheckedChange={setShowJSONProperties}
                        asChild
                    >
                        <ButtonPrimitive menuItem size="sm">
                            <DropdownMenuItemIndicator intent="checkbox" />
                            As JSON
                        </ButtonPrimitive>
                    </DropdownMenuCheckboxItem>
                </DropdownMenuGroup>
            </DropdownMenuContent>
        </DropdownMenu>
    )
}
