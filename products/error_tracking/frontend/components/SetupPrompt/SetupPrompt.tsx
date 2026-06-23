import { useActions, useValues } from 'kea'
import { type ComponentType, isValidElement } from 'react'

import { LemonButton, Link, Spinner } from '@posthog/lemon-ui'

import { WarningHog } from 'lib/components/hedgehogs'
import {
    ProductIntroduction,
    type ProductIntroductionProps,
} from 'lib/components/ProductIntroduction/ProductIntroduction'
import { RestrictionScope, useRestrictedArea } from 'lib/components/RestrictedArea'
import { TeamMembershipLevel } from 'lib/constants'
import { cn } from 'lib/utils/css-classes'
import androidImage from 'scenes/onboarding/legacy/sdks/logos/android.svg'
import flutterImage from 'scenes/onboarding/legacy/sdks/logos/flutter.svg'
import { IOSLogo } from 'scenes/onboarding/legacy/sdks/logos/IOSLogo'
import javascriptImage from 'scenes/onboarding/legacy/sdks/logos/javascript_web.svg'
import nextjsImage from 'scenes/onboarding/legacy/sdks/logos/nextjs.svg'
import nodejsImage from 'scenes/onboarding/legacy/sdks/logos/nodejs.svg'
import pythonImage from 'scenes/onboarding/legacy/sdks/logos/python.svg'
import reactImage from 'scenes/onboarding/legacy/sdks/logos/react.svg'
import { teamLogic } from 'scenes/teamLogic'

import { ProductIntentContext, ProductKey } from '~/queries/schema/schema-general'

import { exceptionIngestionLogic } from './exceptionIngestionLogic'

export const ERROR_TRACKING_FRAMEWORK_LINKS: {
    name: string
    image?: string | JSX.Element
    docsLink: string
}[] = [
    {
        name: 'JavaScript',
        image: javascriptImage,
        docsLink: 'https://posthog.com/docs/error-tracking/installation/web',
    },
    { name: 'Next.js', image: nextjsImage, docsLink: 'https://posthog.com/docs/error-tracking/installation/nextjs' },
    { name: 'React', image: reactImage, docsLink: 'https://posthog.com/docs/error-tracking/installation/react' },
    { name: 'Node.js', image: nodejsImage, docsLink: 'https://posthog.com/docs/error-tracking/installation/nodejs' },
    { name: 'Python', image: pythonImage, docsLink: 'https://posthog.com/docs/error-tracking/installation/python' },
    { name: 'iOS', image: <IOSLogo />, docsLink: 'https://posthog.com/docs/error-tracking/installation/ios' },
    { name: 'Android', image: androidImage, docsLink: 'https://posthog.com/docs/error-tracking/installation/android' },
    {
        name: 'React Native',
        image: reactImage,
        docsLink: 'https://posthog.com/docs/error-tracking/installation/react-native',
    },
    { name: 'Flutter', image: flutterImage, docsLink: 'https://posthog.com/docs/error-tracking/installation/flutter' },
    { name: 'Other', docsLink: 'https://posthog.com/docs/error-tracking/installation' },
]

export const ErrorTrackingSetupPrompt = ({
    children,
    className,
}: {
    children: React.ReactNode
    className?: string
}): JSX.Element => {
    const { hasSentExceptionEvent, hasSentExceptionEventLoading } = useValues(exceptionIngestionLogic)
    const { currentTeam } = useValues(teamLogic)
    const exceptionAutocaptureEnabled = currentTeam && currentTeam.autocapture_exceptions_opt_in

    return hasSentExceptionEventLoading || !currentTeam ? (
        <div className="flex justify-center">
            <Spinner />
        </div>
    ) : !hasSentExceptionEvent && !exceptionAutocaptureEnabled ? (
        <ErrorTrackingIngestionPrompt className={className} />
    ) : (
        <>{children}</>
    )
}

export type ErrorTrackingIngestionPromptProps = {
    className?: string
    /** Passed to `IntroductionComponent` (e.g. `WidgetCardProductIntroduction--stacked`). */
    introductionClassName?: string
    /** When true, passed through to `WidgetCardProductIntroduction` for always-vertical layout. */
    introductionStacked?: boolean
    IntroductionComponent?: ComponentType<ProductIntroductionProps>
    actionElementClassName?: string
}

export function ErrorTrackingIngestionPrompt({
    className,
    introductionClassName,
    introductionStacked,
    IntroductionComponent = ProductIntroduction,
    actionElementClassName = 'flex flex-col items-start gap-4',
}: ErrorTrackingIngestionPromptProps): JSX.Element {
    const { addProductIntent, updateCurrentTeam } = useActions(teamLogic)
    const restrictionReason = useRestrictedArea({
        minimumAccessLevel: TeamMembershipLevel.Admin,
        scope: RestrictionScope.Project,
    })

    const onDocsLinkClick = (): void => {
        addProductIntent({
            product_type: ProductKey.ERROR_TRACKING,
            intent_context: ProductIntentContext.ERROR_TRACKING_DOCS_VIEWED,
        })
    }

    return (
        <IntroductionComponent
            productName="Error tracking"
            thingName="issue"
            titleOverride="You haven't captured any exceptions"
            description="PostHog captures exceptions from any of our SDKs. JavaScript apps can flip on exception autocapture; other platforms wire it up in code – the docs have per-SDK instructions."
            isEmpty={true}
            productKey={ProductKey.ERROR_TRACKING}
            className={cn(introductionClassName, className)}
            {...(introductionStacked !== undefined ? { stacked: introductionStacked } : {})}
            mcpSurfaceKey="error_tracking.assign"
            customHog={WarningHog}
            actionElementOverride={
                <div className={actionElementClassName}>
                    <p className="text-sm text-secondary m-0">
                        Read our{' '}
                        <Link to="https://posthog.com/docs/error-tracking" onClick={onDocsLinkClick}>
                            error tracking docs
                        </Link>
                        , or pick a framework to get started:
                    </p>
                    <div className="flex flex-wrap gap-2">
                        {ERROR_TRACKING_FRAMEWORK_LINKS.map(({ name, image, docsLink }) => (
                            <LemonButton
                                key={name}
                                type="secondary"
                                size="small"
                                to={docsLink}
                                targetBlank
                                onClick={onDocsLinkClick}
                                icon={
                                    isValidElement(image) ? (
                                        <span className="flex w-5 h-5 [&_svg]:w-full [&_svg]:h-full">{image}</span>
                                    ) : typeof image === 'string' ? (
                                        <img src={image} alt="" aria-hidden="true" className="w-5 h-5" />
                                    ) : undefined
                                }
                            >
                                {name}
                            </LemonButton>
                        ))}
                    </div>
                    <p className="text-sm text-secondary m-0">
                        Already using <code>posthog-js</code>?{' '}
                        <LemonButton
                            type="primary"
                            size="small"
                            disabledReason={restrictionReason}
                            onClick={() => {
                                addProductIntent({
                                    product_type: ProductKey.ERROR_TRACKING,
                                    intent_context: ProductIntentContext.ERROR_TRACKING_EXCEPTION_AUTOCAPTURE_ENABLED,
                                })
                                updateCurrentTeam({ autocapture_exceptions_opt_in: true })
                            }}
                        >
                            Enable exception autocapture
                        </LemonButton>
                    </p>
                </div>
            }
        />
    )
}
