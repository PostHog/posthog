import { match } from 'ts-pattern'

import { IconBug, IconCheckCircle, IconSparkles, IconWarning } from '@posthog/icons'
import { LemonTag, Spinner } from '@posthog/lemon-ui'

import { ExceptionAttributes } from 'lib/components/Errors/types'
import { concatValues } from 'lib/components/Errors/utils'
import { PropertyIcon } from 'lib/components/PropertyIcon/PropertyIcon'

export interface ExceptionAttributesPreviewProps {
    attributes: ExceptionAttributes | null
    loading?: boolean
}

export function ExceptionAttributesPreview({
    attributes,
    loading = false,
}: ExceptionAttributesPreviewProps): JSX.Element {
    return (
        <>
            {match(loading)
                .with(true, () => (
                    <span className="text-muted space-x-2 text-xs">
                        <Spinner />
                        <span>Loading details...</span>
                    </span>
                ))
                .with(
                    false,
                    () =>
                        attributes && (
                            <>
                                {attributes.level ? (
                                    <LemonTag className="gap-1.5 bg-fill-primary">
                                        <IconWarning />
                                        <span className="capitalize">{attributes.level}</span>
                                    </LemonTag>
                                ) : null}
                                {attributes.handled !== undefined ? (
                                    <LemonTag className="gap-1.5 bg-fill-primary">
                                        {attributes.handled ? <IconCheckCircle /> : <IconBug />}
                                        {attributes.handled ? 'Handled' : 'Unhandled'}
                                    </LemonTag>
                                ) : null}
                                {attributes.synthetic ? (
                                    <LemonTag className="gap-1.5 bg-fill-primary">
                                        <IconSparkles />
                                        Synthetic
                                    </LemonTag>
                                ) : null}
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
                )
                .exhaustive()}
        </>
    )
}
