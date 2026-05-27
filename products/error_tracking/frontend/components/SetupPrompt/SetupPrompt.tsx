import { useActions, useValues } from 'kea'

import { LemonButton, Link, Spinner } from '@posthog/lemon-ui'

import { WarningHog } from 'lib/components/hedgehogs'
import { ProductIntroduction } from 'lib/components/ProductIntroduction/ProductIntroduction'
import { RestrictionScope, useRestrictedArea } from 'lib/components/RestrictedArea'
import { TeamMembershipLevel } from 'lib/constants'
import androidImage from 'scenes/onboarding/sdks/logos/android.svg'
import flutterImage from 'scenes/onboarding/sdks/logos/flutter.svg'
import javascriptImage from 'scenes/onboarding/sdks/logos/javascript_web.svg'
import nextjsImage from 'scenes/onboarding/sdks/logos/nextjs.svg'
import nodejsImage from 'scenes/onboarding/sdks/logos/nodejs.svg'
import pythonImage from 'scenes/onboarding/sdks/logos/python.svg'
import reactImage from 'scenes/onboarding/sdks/logos/react.svg'
import { teamLogic } from 'scenes/teamLogic'

import { ProductIntentContext, ProductKey } from '~/queries/schema/schema-general'

import { exceptionIngestionLogic } from './exceptionIngestionLogic'

const FRAMEWORK_LINKS: { name: string; image?: string; docsLink: string }[] = [
    {
        name: 'JavaScript',
        image: javascriptImage,
        docsLink: 'https://posthog.com/docs/error-tracking/installation/web',
    },
    { name: 'Next.js', image: nextjsImage, docsLink: 'https://posthog.com/docs/error-tracking/installation/nextjs' },
    { name: 'React', image: reactImage, docsLink: 'https://posthog.com/docs/error-tracking/installation/react' },
    { name: 'Node.js', image: nodejsImage, docsLink: 'https://posthog.com/docs/error-tracking/installation/nodejs' },
    { name: 'Python', image: pythonImage, docsLink: 'https://posthog.com/docs/error-tracking/installation/python' },
    { name: 'iOS', docsLink: 'https://posthog.com/docs/error-tracking/installation/ios' },
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
        <IngestionStatusCheck className={className} />
    ) : (
        <>{children}</>
    )
}

const IngestionStatusCheck = ({ className }: { className?: string }): JSX.Element | null => {
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
        <ProductIntroduction
            productName="Error tracking"
            thingName="issue"
            titleOverride="You haven't captured any exceptions"
            description="PostHog captures exceptions from any of our SDKs. JavaScript apps can flip on exception autocapture; other platforms wire it up in code – the docs have per-SDK instructions."
            isEmpty={true}
            productKey={ProductKey.ERROR_TRACKING}
            className={className}
            customHog={WarningHog}
            actionElementOverride={
                <div className="flex flex-col items-start gap-4">
                    <p className="text-sm text-secondary m-0">
                        Read our{' '}
                        <Link to="https://posthog.com/docs/error-tracking" onClick={onDocsLinkClick}>
                            error tracking docs
                        </Link>
                        , or pick a framework to get started:
                    </p>
                    <div className="flex flex-wrap gap-2">
                        {FRAMEWORK_LINKS.map(({ name, image, docsLink }) => (
                            <LemonButton
                                key={name}
                                type="secondary"
                                size="small"
                                to={docsLink}
                                targetBlank
                                onClick={onDocsLinkClick}
                                icon={
                                    image ? (
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
