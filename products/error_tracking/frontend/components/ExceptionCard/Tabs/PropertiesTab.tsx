import { useActions, useValues } from 'kea'
import type { ChangeEvent, ComponentProps } from 'react'

import { IconSearch } from '@posthog/icons'

import { errorPropertiesLogic } from 'lib/components/Errors/errorPropertiesLogic'
import { JSONViewer } from 'lib/components/JSONViewer'
import { InputGroup, InputGroupAddon, InputGroupInput, Label, Switch, TabsContent } from 'lib/ui/quill'
import { cn } from 'lib/utils/css-classes'

import { ContextDisplay } from '../../ContextDisplay/ContextDisplay'
import { exceptionCardLogic } from '../exceptionCardLogic'
import { SubHeader } from './SubHeader'

export type PropertiesTabProps = ComponentProps<typeof TabsContent>

export function PropertiesTab({ className, ...props }: PropertiesTabProps): JSX.Element {
    const { properties, additionalProperties } = useValues(errorPropertiesLogic)
    const { loading, propertyNameFilter, showJSONProperties } = useValues(exceptionCardLogic)
    const { setPropertyNameFilter, setShowJSONProperties } = useActions(exceptionCardLogic)
    const filteredProperties = filterPropertiesByName(properties, propertyNameFilter)

    return (
        <TabsContent {...props} className={cn('flex flex-col', className)}>
            <SubHeader className="shrink-0 justify-between gap-2">
                <div className="w-64 max-w-full min-w-0">
                    <InputGroup className="h-6 border-muted-foreground/20 focus-within:border-ring/50">
                        <InputGroupAddon>
                            <IconSearch />
                        </InputGroupAddon>
                        <InputGroupInput
                            type="search"
                            value={propertyNameFilter}
                            onChange={(event: ChangeEvent<HTMLInputElement>) =>
                                setPropertyNameFilter(event.target.value)
                            }
                            placeholder="Filter properties"
                            aria-label="Filter properties"
                        />
                    </InputGroup>
                </div>
                <Label htmlFor="exception-properties-json-switch" className="cursor-pointer">
                    JSON
                    <Switch
                        id="exception-properties-json-switch"
                        checked={showJSONProperties}
                        onCheckedChange={setShowJSONProperties}
                        size="sm"
                        data-attr="exception-properties-json-switch"
                    />
                </Label>
            </SubHeader>
            <div className="flex-1 min-h-0 overflow-y-auto">
                {showJSONProperties ? (
                    <JSONViewer
                        src={filteredProperties}
                        name="event"
                        collapsed={1}
                        collapseStringsAfterLength={80}
                        sortKeys
                    />
                ) : (
                    <ContextDisplay
                        loading={loading}
                        properties={properties}
                        additionalProperties={additionalProperties}
                        propertyNameFilter={propertyNameFilter}
                    />
                )}
            </div>
        </TabsContent>
    )
}

function filterPropertiesByName(
    properties: Record<string, unknown> | undefined,
    propertyNameFilter: string
): Record<string, unknown> {
    const normalizedPropertyNameFilter = propertyNameFilter.trim().toLocaleLowerCase()
    if (!normalizedPropertyNameFilter) {
        return properties ?? {}
    }

    return Object.fromEntries(
        Object.entries(properties ?? {}).filter(([key]) =>
            key.toLocaleLowerCase().includes(normalizedPropertyNameFilter)
        )
    )
}
