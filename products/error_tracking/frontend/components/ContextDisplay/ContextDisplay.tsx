import { match } from 'ts-pattern'

import { Spinner } from '@posthog/lemon-ui'

import { ExceptionAttributes } from 'lib/components/Errors/types'
import { concatValues } from 'lib/components/Errors/utils'
import { identifierToHuman } from 'lib/utils'

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
              ['App', concatValues(exceptionAttributes, 'appNamespace', 'appVersion')],
              ['OS', concatValues(exceptionAttributes, 'os', 'osVersion')],
              ['URL', exceptionAttributes.url],
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
                .with(false, () => <PropertiesTable entries={[...exceptionEntries, ...additionalEntries]} />)
                .exhaustive()}
        </>
    )
}
