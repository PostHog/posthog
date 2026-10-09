import { useActions, useValues } from 'kea'

import { LemonBanner, LemonDialog, LemonSkeleton, LemonSwitch } from '@posthog/lemon-ui'

import { errorTrackingEditAccessDisabledReason } from '../../../utils'
import { exceptionIngestionLogic } from './exceptionIngestionLogic'

export function ExceptionIngestionSettings(): JSX.Element {
    const { ingestionEnabled, settingsLoading, settingsLoadFailed } = useValues(exceptionIngestionLogic)
    const { setIngestionEnabled } = useActions(exceptionIngestionLogic)

    const onChange = (checked: boolean): void => {
        if (checked) {
            setIngestionEnabled(true)
            return
        }
        LemonDialog.open({
            title: 'Stop ingesting exceptions?',
            description:
                "PostHog will drop every exception this project sends until you turn ingestion back on. You can't recover dropped exceptions.",
            primaryButton: {
                children: 'Stop ingesting',
                status: 'danger',
                onClick: () => setIngestionEnabled(false),
                'data-attr': 'error-tracking-ingestion-disable-confirm',
            },
            secondaryButton: { children: 'Cancel' },
        })
    }

    return (
        <div className="space-y-4">
            <div>
                <h3 className="font-semibold text-base mb-1">Exception ingestion</h3>
                <p className="text-muted-foreground">
                    When this is off, PostHog drops every exception this project sends. Dropped exceptions aren't stored
                    or billed, and you can't recover them. Changes take up to a minute to apply.
                </p>
            </div>
            {ingestionEnabled !== null ? (
                <LemonSwitch
                    id="error-tracking-ingestion-switch"
                    data-attr="error-tracking-ingestion-switch"
                    label="Ingest exceptions"
                    checked={ingestionEnabled}
                    onChange={onChange}
                    loading={settingsLoading}
                    disabledReason={errorTrackingEditAccessDisabledReason()}
                    bordered
                />
            ) : settingsLoadFailed ? (
                <LemonBanner type="error">Couldn't load this setting. Refresh the page to try again.</LemonBanner>
            ) : (
                <LemonSkeleton className="w-60 h-10" />
            )}
        </div>
    )
}
