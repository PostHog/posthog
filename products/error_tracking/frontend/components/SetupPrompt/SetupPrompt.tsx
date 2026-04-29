import { useActions, useValues } from 'kea'

import { IconExternal } from '@posthog/icons'
import { LemonButton, Spinner } from '@posthog/lemon-ui'

import { ProductIntroduction } from 'lib/components/ProductIntroduction/ProductIntroduction'
import { RestrictionScope, useRestrictedArea } from 'lib/components/RestrictedArea'
import { TeamMembershipLevel } from 'lib/constants'
import { teamLogic } from 'scenes/teamLogic'

import { ProductIntentContext, ProductKey } from '~/queries/schema/schema-general'

import { exceptionIngestionLogic } from './exceptionIngestionLogic'

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

    return (
        <ProductIntroduction
            productName="Error tracking"
            thingName="issue"
            titleOverride="You haven't captured any exceptions yet"
            description="If you haven't installed an SDK yet, follow the docs for your platform. JS users can also flip on exception autocapture below — non-JS SDKs (Python, Node, etc.) capture exceptions through SDK config and don't need this toggle. If your SDK is already configured but events aren't showing up, check the self-hosted ingestion troubleshooting guide."
            isEmpty={true}
            productKey={ProductKey.ERROR_TRACKING}
            className={className}
            actionElementOverride={
                <>
                    <LemonButton
                        type="primary"
                        disabledReason={restrictionReason}
                        onClick={() => {
                            addProductIntent({
                                product_type: ProductKey.ERROR_TRACKING,
                                intent_context: ProductIntentContext.ERROR_TRACKING_EXCEPTION_AUTOCAPTURE_ENABLED,
                            })
                            updateCurrentTeam({ autocapture_exceptions_opt_in: true })
                        }}
                    >
                        Enable JS exception autocapture
                    </LemonButton>
                    <LemonButton
                        targetBlank
                        sideIcon={<IconExternal className="w-5 h-5" />}
                        to="https://posthog.com/docs/error-tracking/installation"
                        onClick={() => {
                            addProductIntent({
                                product_type: ProductKey.ERROR_TRACKING,
                                intent_context: ProductIntentContext.ERROR_TRACKING_DOCS_VIEWED,
                            })
                        }}
                    >
                        Read the docs
                    </LemonButton>
                    <LemonButton
                        targetBlank
                        sideIcon={<IconExternal className="w-5 h-5" />}
                        to="https://posthog.com/docs/self-host/troubleshooting"
                    >
                        Self-hosted troubleshooting
                    </LemonButton>
                </>
            }
        />
    )
}
