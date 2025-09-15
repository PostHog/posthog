import { useActions, useValues } from 'kea'

import { IconExternal } from '@posthog/icons'
import { LemonButton, Spinner } from '@posthog/lemon-ui'

import { ProductIntroduction } from 'lib/components/ProductIntroduction/ProductIntroduction'
import { ProductIntentContext } from 'lib/utils/product-intents'
import { teamLogic } from 'scenes/teamLogic'

import { ProductKey } from '~/types'

import { exceptionIngestionLogic } from './exceptionIngestionLogic'

export const ErrorTrackingSetupPrompt = ({ children }: { children: React.ReactNode }): JSX.Element => {
    const { hasSentExceptionEvent, hasSentExceptionEventLoading } = useValues(exceptionIngestionLogic)
    const { currentTeam, currentTeamLoading } = useValues(teamLogic)
    const exceptionAutocaptureEnabled = currentTeam && currentTeam.autocapture_exceptions_opt_in

    return hasSentExceptionEventLoading || currentTeamLoading ? (
        <div className="flex justify-center">
            <Spinner />
        </div>
    ) : !hasSentExceptionEvent && !exceptionAutocaptureEnabled ? (
        <IngestionStatusCheck />
    ) : (
        <>{children}</>
    )
}

const IngestionStatusCheck = (): JSX.Element | null => {
    const { addProductIntent, updateCurrentTeam } = useActions(teamLogic)

    return (
        <ProductIntroduction
            productName="Error tracking"
            thingName="issue"
            titleOverride="You haven't captured any exceptions"
            description="To start capturing exceptions you need to enable exception autocapture. Exception autocapture only applies to the JS SDK. Installation for other platforms are described in the docs."
            isEmpty={true}
            productKey={ProductKey.ERROR_TRACKING}
            actionElementOverride={
                <>
                    <LemonButton
                        type="primary"
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
                </>
            }
        />
    )
}
