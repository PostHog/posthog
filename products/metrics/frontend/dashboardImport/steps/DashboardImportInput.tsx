import { useActions, useValues } from 'kea'
import { useRef } from 'react'

import { IconUpload } from '@posthog/icons'
import { LemonBanner, LemonButton, LemonFileInput, LemonInput, LemonTextArea } from '@posthog/lemon-ui'

import { LemonField } from 'lib/lemon-ui/LemonField'

import { metricsDashboardImportLogic } from '../metricsDashboardImportLogic'
import { SCREENSHOT_TYPES } from '../readScreenshot'

export function DashboardImportInput(): JSX.Element {
    const {
        source,
        grafanaJson,
        grafanaJsonError,
        dashboardName,
        screenshot,
        screenshotLoading,
        screenshotError,
        startError,
        starting,
    } = useValues(metricsDashboardImportLogic)
    const { setGrafanaJson, setDashboardName, setScreenshotFile, setScreenshot } =
        useActions(metricsDashboardImportLogic)
    const dropZoneRef = useRef<HTMLDivElement>(null)

    const onPaste = (event: React.ClipboardEvent<HTMLDivElement>): void => {
        const image = Array.from(event.clipboardData.files).find((file) => SCREENSHOT_TYPES.includes(file.type))
        if (source === 'screenshot' && image && !starting) {
            event.preventDefault()
            setScreenshotFile(image)
        }
    }

    return (
        <div className="flex flex-col gap-4" onPaste={onPaste}>
            <p className="m-0 text-secondary">
                {source === 'grafana'
                    ? 'PostHog AI rebuilds each panel with the metrics, logs and traces of this project. At the end, you see which panels did not import. This uses AI credits.'
                    : 'PostHog AI reads the panels in the screenshot and rebuilds them with the metrics, logs and traces of this project. This uses AI credits.'}
            </p>
            {source === 'grafana' ? (
                <LemonField.Pure
                    label="Grafana dashboard JSON"
                    help="In Grafana, open the dashboard settings and copy the JSON model. You can also export the dashboard as JSON."
                    error={grafanaJsonError}
                >
                    <LemonTextArea
                        value={grafanaJson}
                        onChange={setGrafanaJson}
                        placeholder='{ "title": "Service overview", "panels": [ ... ] }'
                        minRows={8}
                        maxRows={16}
                        className="font-mono text-xs"
                        disabled={starting}
                        autoFocus
                        data-attr="metrics-dashboard-import-grafana-json"
                    />
                </LemonField.Pure>
            ) : (
                <LemonField.Pure
                    label="Screenshot"
                    help="Use a screenshot of the full dashboard in which you can read the panel titles."
                    error={screenshotError}
                >
                    {screenshot ? (
                        <div className="flex flex-col items-start gap-2">
                            <img
                                src={screenshot}
                                alt="The dashboard screenshot to import"
                                className="max-h-72 w-full object-contain rounded border bg-surface-secondary"
                            />
                            <LemonButton
                                type="secondary"
                                size="small"
                                onClick={() => setScreenshot(null)}
                                disabledReason={starting ? 'The import is starting' : undefined}
                            >
                                Remove screenshot
                            </LemonButton>
                        </div>
                    ) : (
                        <div
                            ref={dropZoneRef}
                            className="flex flex-col items-center gap-2 rounded border border-dashed p-6 text-center"
                        >
                            <LemonFileInput
                                accept={SCREENSHOT_TYPES.join(',')}
                                multiple={false}
                                showUploadedFiles={false}
                                loading={screenshotLoading}
                                alternativeDropTargetRef={dropZoneRef}
                                onChange={(files) => files[0] && setScreenshotFile(files[0])}
                                callToAction={
                                    <LemonButton
                                        type="secondary"
                                        size="small"
                                        icon={<IconUpload />}
                                        loading={screenshotLoading}
                                        data-attr="metrics-dashboard-import-choose-screenshot"
                                    >
                                        Choose a screenshot
                                    </LemonButton>
                                }
                            />
                            <span className="text-xs text-secondary">You can also drop or paste the image here.</span>
                        </div>
                    )}
                </LemonField.Pure>
            )}
            <LemonField.Pure
                label="Dashboard name"
                help={
                    source === 'grafana'
                        ? 'Leave this empty to use the title of the Grafana dashboard.'
                        : 'Leave this empty to use the title in the screenshot.'
                }
            >
                <LemonInput
                    value={dashboardName}
                    onChange={setDashboardName}
                    placeholder="Optional"
                    maxLength={400}
                    disabled={starting}
                    autoFocus={source === 'screenshot'}
                    data-attr="metrics-dashboard-import-name"
                />
            </LemonField.Pure>
            {startError && <LemonBanner type="error">{startError}</LemonBanner>}
        </div>
    )
}
