import { useValues } from 'kea'

import { LemonBanner } from '@posthog/lemon-ui'

import { ErrorEventType } from 'lib/components/Errors/types'
import { Link } from 'lib/lemon-ui/Link'

import { codeVariablesBannerLogic } from './codeVariablesBannerLogic'

interface CodeVariablesBannerProps {
    event?: ErrorEventType | null
}

export function CodeVariablesBanner(props: CodeVariablesBannerProps): JSX.Element | null {
    if (!props.event || !props.event.properties || !props.event.uuid) {
        return null
    }

    return <CodeVariablesBannerContent event={props.event} />
}

export function CodeVariablesBannerContent({ event }: { event: ErrorEventType }): JSX.Element | null {
    const { shouldShowBanner } = useValues(
        codeVariablesBannerLogic({
            properties: event.properties,
            id: event.uuid,
        })
    )

    if (!shouldShowBanner) {
        return null
    }

    return (
        <LemonBanner type="info" dismissKey="code-variables-python-banner" className="mb-4">
            It looks like you are not using our code variables feature.{' '}
            <Link to="https://posthog.com/docs/error-tracking/code-variables" target="_blank">
                Learn more
            </Link>
        </LemonBanner>
    )
}
