import { Link } from '@posthog/lemon-ui'
import { Button } from '@posthog/quill'

import { FEATURE_SUPPORT } from 'lib/components/SupportedPlatforms/featureSupport'
import { QuillSupportedPlatforms } from 'lib/components/SupportedPlatforms/QuillSupportedPlatforms'
import { SupportedPlatforms } from 'lib/components/SupportedPlatforms/SupportedPlatforms'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { LinkPrimitive } from 'lib/lemon-ui/Link'

import { AdaptiveIngestionSetting } from '../adaptive_ingestion/AdaptiveIngestionSetting'
import { ExceptionAutocaptureToggle } from '../exception_autocapture/ExceptionAutocaptureSettings'
import { QuillConfigurationSubsection } from '../QuillConfigurationSubsection'
import { ExceptionIngestionSettings } from './ExceptionIngestionSettings'

export function GeneralSettings(): JSX.Element {
    const showAdaptiveIngestion = useFeatureFlag('ERROR_TRACKING_ADAPTIVE_INGESTION')
    const todayRailNav = useFeatureFlag('TODAY_RAIL_NAV')

    if (todayRailNav) {
        return (
            <div className="flex flex-col gap-8">
                <ExceptionIngestionSettings />
                {showAdaptiveIngestion && (
                    <QuillConfigurationSubsection
                        title="Adaptive ingestion"
                        description="Automatic error sampling is not available yet. Your existing rate limits still apply."
                    >
                        <AdaptiveIngestionSetting />
                    </QuillConfigurationSubsection>
                )}
                <QuillConfigurationSubsection
                    title="Exception autocapture"
                    titleExtra={<QuillSupportedPlatforms config={FEATURE_SUPPORT.errorTrackingExceptionAutocapture} />}
                    description={
                        <>
                            Automatically capture frontend exceptions using onError and onUnhandledRejection listeners
                            in the web JavaScript SDK.{' '}
                            <Button
                                variant="link"
                                size="inline"
                                nativeButton={false}
                                render={<LinkPrimitive to="https://posthog.com/docs/error-tracking" target="_blank" />}
                                data-attr="settings-docs-link-error-tracking-exception-autocapture"
                            >
                                Docs
                            </Button>
                        </>
                    }
                >
                    <ExceptionAutocaptureToggle />
                </QuillConfigurationSubsection>
            </div>
        )
    }

    return (
        <div className="space-y-8">
            <ExceptionIngestionSettings />
            {showAdaptiveIngestion && (
                <div className="space-y-4">
                    <div>
                        <h3 className="font-semibold text-base mb-1">Adaptive ingestion</h3>
                        <p className="text-muted-foreground">
                            Automatic error sampling is not available yet. Your existing rate limits still apply.
                        </p>
                    </div>
                    <AdaptiveIngestionSetting />
                </div>
            )}
            <div className="space-y-4">
                <div>
                    <h3 className="flex flex-wrap gap-2 items-center font-semibold text-base mb-1">
                        Exception autocapture
                        <SupportedPlatforms config={FEATURE_SUPPORT.errorTrackingExceptionAutocapture} />
                    </h3>
                    <p className="text-muted-foreground">
                        Automatically capture frontend exceptions using onError and onUnhandledRejection listeners in
                        the web JavaScript SDK.{' '}
                        <Link
                            to="https://posthog.com/docs/error-tracking"
                            target="_blank"
                            data-attr="settings-docs-link-error-tracking-exception-autocapture"
                        >
                            Docs
                        </Link>
                    </p>
                </div>
                <ExceptionAutocaptureToggle />
            </div>
        </div>
    )
}
