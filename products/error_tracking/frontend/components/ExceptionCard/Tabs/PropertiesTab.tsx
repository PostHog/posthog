import { useActions, useValues } from 'kea'
import type { ComponentProps } from 'react'

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
import { TabsContent } from 'lib/ui/quill'
import { cn } from 'lib/utils/css-classes'

import { ContextDisplay } from '../../ContextDisplay/ContextDisplay'
import { exceptionCardLogic } from '../exceptionCardLogic'
import { SubHeader } from './SubHeader'

export interface PropertiesTabProps extends ComponentProps<typeof TabsContent> {}

export function PropertiesTab({ className, ...props }: PropertiesTabProps): JSX.Element {
    const { properties, exceptionAttributes, additionalProperties } = useValues(errorPropertiesLogic)
    const { loading, showJSONProperties, showAdditionalProperties } = useValues(exceptionCardLogic)

    return (
        <TabsContent {...props} className={cn('flex flex-col', className)}>
            <SubHeader className="justify-end shrink-0">
                <div className="contents">
                    <ShowDropDownMenu />
                </div>
            </SubHeader>
            <div className="flex-1 min-h-0 overflow-y-auto">
                {showJSONProperties ? (
                    <div className="contents">
                        <JSONViewer
                            src={properties}
                            name="event"
                            collapsed={1}
                            collapseStringsAfterLength={80}
                            sortKeys
                        />
                    </div>
                ) : (
                    <ContextDisplay
                        loading={loading}
                        exceptionAttributes={exceptionAttributes}
                        additionalProperties={showAdditionalProperties ? additionalProperties : {}}
                    />
                )}
            </div>
        </TabsContent>
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
