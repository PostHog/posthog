import { Link } from '@posthog/lemon-ui'

import { FEATURE_SUPPORT } from 'lib/components/SupportedPlatforms/featureSupport'
import { SupportedPlatforms } from 'lib/components/SupportedPlatforms/SupportedPlatforms'

import { ExceptionAutocaptureToggle } from '../exception_autocapture/ExceptionAutocaptureSettings'
import { ExceptionIngestionSettings } from './ExceptionIngestionSettings'

export function GeneralSettings(): JSX.Element {
    return (
        <div className="space-y-8">
            <ExceptionIngestionSettings />
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
