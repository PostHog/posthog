import { useActions } from 'kea'
import { match } from 'ts-pattern'

import { Spinner } from '@posthog/lemon-ui'

import { ExceptionAttributes } from 'lib/components/Errors/types'
import { concatValues } from 'lib/components/Errors/utils'
import { identifierToHuman } from 'lib/utils'

import { propertyValueFilterLogic } from '../ExceptionCard/propertyValueFilterLogic'
import { PropertiesTable } from '../PropertiesTable'

export type ContextDisplayProps = {
    loading: boolean
    exceptionAttributes: ExceptionAttributes | null
    additionalProperties: Record<string, unknown>
}

export function ContextDisplay({
    loading,
    exceptionAttributes,
    additionalProperties,
}: ContextDisplayProps): JSX.Element {
    const { filterByPropertyValue } = useActions(propertyValueFilterLogic)
    const additionalEntries = Object.entries(additionalProperties)
        .sort(([leftKey], [rightKey]) => leftKey.localeCompare(rightKey, undefined, { sensitivity: 'base' }))
        .map(([key, value]) => ({ key: identifierToHuman(key, 'title'), value, filterKey: key }))
    const exceptionEntries = exceptionAttributes
        ? [
              { key: 'Level', value: exceptionAttributes.level, filterKey: '$level' },
              { key: 'Synthetic', value: exceptionAttributes.synthetic, filterKey: '$exception_synthetic' },
              {
                  key: 'Library',
                  value: concatValues(exceptionAttributes, 'lib', 'libVersion'),
                  filterKey: '$lib',
                  filterValue: exceptionAttributes.lib,
              },
              { key: 'Handled', value: exceptionAttributes.handled },
              {
                  key: 'Browser',
                  value: concatValues(exceptionAttributes, 'browser', 'browserVersion'),
                  filterKey: '$browser',
                  filterValue: exceptionAttributes.browser,
              },
              {
                  key: 'App',
                  value: concatValues(exceptionAttributes, 'appNamespace', 'appVersion'),
                  filterKey: '$app_namespace',
                  filterValue: exceptionAttributes.appNamespace,
              },
              {
                  key: 'OS',
                  value: concatValues(exceptionAttributes, 'os', 'osVersion'),
                  filterKey: '$os',
                  filterValue: exceptionAttributes.os,
              },
              { key: 'URL', value: exceptionAttributes.url, filterKey: '$current_url' },
          ]
        : []

    return (
        <>
            {match(loading)
                .with(true, () => (
                    <div className="flex justify-center w-full h-32 items-center">
                        <Spinner />
                    </div>
                ))
                .with(false, () => (
                    <PropertiesTable
                        entries={[...exceptionEntries, ...additionalEntries]}
                        onFilterValue={filterByPropertyValue}
                    />
                ))
                .exhaustive()}
        </>
    )
}
