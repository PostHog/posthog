import { LemonTag } from '@posthog/lemon-ui'

import { ExceptionAttributes } from 'lib/components/Errors/types'
import { concatValues } from 'lib/components/Errors/utils'
import { PropertyIcon } from 'lib/components/PropertyIcon/PropertyIcon'

export interface ExceptionPlatformPillsProps {
    attributes: ExceptionAttributes | null
}

export function ExceptionPlatformPills({ attributes }: ExceptionPlatformPillsProps): JSX.Element | null {
    if (!attributes) {
        return null
    }
    return (
        <>
            {attributes.browser ? (
                <LemonTag className="gap-1.5 bg-fill-primary">
                    <PropertyIcon property="$browser" value={attributes.browser} />
                    <span>{concatValues(attributes, 'browser', 'browserVersion')}</span>
                </LemonTag>
            ) : null}
            {attributes.os ? (
                <LemonTag className="gap-1.5 bg-fill-primary">
                    <PropertyIcon property="$os" value={attributes.os} />
                    <span>{concatValues(attributes, 'os', 'osVersion')}</span>
                </LemonTag>
            ) : null}
        </>
    )
}
