import { useActions, useValues } from 'kea'
import useResizeObserver from 'use-resize-observer'

import { IconBrowser, IconCheckCircle, IconImage, IconWarning } from '@posthog/icons'
import {
    LemonBanner,
    LemonButton,
    LemonCard,
    LemonCollapse,
    LemonLabel,
    LemonSegmentedButton,
    Spinner,
} from '@posthog/lemon-ui'

import { AccessControlAction } from 'lib/components/AccessControlAction'
import { appEditorUrl } from 'lib/components/AuthorizedUrlList/authorizedUrlListLogic'
import { hasWildcard } from 'lib/components/heatmaps/heatmapUrlMatch'
import { FEATURE_FLAGS } from 'lib/constants'
import { LemonInputSelect } from 'lib/lemon-ui/LemonInputSelect/LemonInputSelect'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { cn } from 'lib/utils/css-classes'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'
import { AccessControlLevel, AccessControlResourceType, HeatmapType } from '~/types'

import { HeatmapAdvancedSettings } from '../../components/HeatmapAdvancedSettings'
import { heatmapCaptureSettingsLogic, isUrlCoveredByAllowlist } from '../../components/heatmapCaptureSettingsLogic'
import { HeatmapPageFields } from '../../components/HeatmapPageFields'
import { HeatmapRecording } from '../../components/HeatmapRecording'
import { HeatmapRecordingFallback } from '../../components/HeatmapRecordingFallback'
import { heatmapsBrowserLogic } from '../../components/heatmapsBrowserLogic'
import { HeatmapScreenshotAccessNotice } from '../../components/HeatmapScreenshotAccessNotice'
import { HeatmapsEnableCapture } from '../../components/HeatmapsEnableCapture'
import { HeatmapsInvalidURL } from '../../components/HeatmapsInvalidURL'
import { HeatmapsPricingNotice } from '../../components/HeatmapsPricingNotice'
import { HeatmapCreationStep, heatmapCreationLogic } from './heatmapCreationLogic'
import { heatmapLogic } from './heatmapLogic'
import { HeatmapNewSceneLegacy } from './HeatmapNewSceneLegacy'

const CREATION_STEPS: { key: HeatmapCreationStep; label: string }[] = [
    { key: 'page', label: 'Page' },
    { key: 'background', label: 'Background' },
    { key: 'review', label: 'Review' },
]

function HeatmapCreationStepper(): JSX.Element {
    const { currentStep, furthestStep, pageAccess, recordingHeatmapOpen } = useValues(heatmapCreationLogic)
    const { navigateToStep } = useActions(heatmapCreationLogic)
    const currentIndex = CREATION_STEPS.findIndex(({ key }) => key === currentStep)
    const furthestIndex = CREATION_STEPS.findIndex(({ key }) => key === furthestStep)

    return (
        <nav
            className="flex flex-wrap items-center gap-2 border-b pb-4 max-w-3xl"
            aria-label="Heatmap creation progress"
        >
            {CREATION_STEPS.map((step, index) => {
                const isCurrent = step.key === currentStep
                const label =
                    step.key === 'review' && recordingHeatmapOpen
                        ? 'Explore'
                        : step.key === 'review' && pageAccess === 'login'
                          ? 'Review background'
                          : step.label

                return (
                    <LemonButton
                        key={step.key}
                        type={isCurrent ? 'primary' : 'tertiary'}
                        size="small"
                        onClick={() => navigateToStep(step.key)}
                        disabled={index > furthestIndex}
                        aria-current={isCurrent ? 'step' : undefined}
                        data-attr={`heatmap-creation-step-${step.key}`}
                        icon={index < currentIndex ? <IconCheckCircle /> : <span>{index + 1}</span>}
                    >
                        {label}
                    </LemonButton>
                )
            })}
        </nav>
    )
}

function CaptureReadiness(): JSX.Element {
    const { captureEnabled } = useValues(heatmapCreationLogic)

    return captureEnabled ? (
        <div className="flex items-center gap-2 text-secondary text-sm">
            <IconCheckCircle className="size-5 shrink-0" />
            <span>Capture enabled</span>
        </div>
    ) : (
        <LemonBanner type="warning">
            <div className="flex flex-col gap-3">
                <div>Capture is off. Enable it to start collecting interactions.</div>
                <HeatmapsEnableCapture />
            </div>
        </LemonBanner>
    )
}

function CaptureUrlReadiness(): JSX.Element | null {
    const { captureEnabled } = useValues(heatmapCreationLogic)
    const { displayUrl } = useValues(heatmapLogic({ id: 'new' }))
    const { currentTeamId } = useValues(teamLogic)
    const { settings, urlAllowlist } = useValues(heatmapCaptureSettingsLogic({ teamId: currentTeamId ?? 0 }))

    if (!captureEnabled || !settings || settings.capture_mode !== 'url_allowlist' || !displayUrl?.trim()) {
        return null
    }

    const covered = isUrlCoveredByAllowlist(displayUrl, urlAllowlist)

    if (covered) {
        return (
            <div className="flex items-center gap-2 text-secondary text-sm">
                <IconCheckCircle className="size-5 shrink-0" />
                <span>Page included in capture URLs</span>
            </div>
        )
    }

    return (
        <LemonBanner
            type="warning"
            action={{ children: 'Manage capture URLs', to: urls.settings('environment-heatmaps') }}
        >
            {settings.enforcement_enabled
                ? 'This page is not in your heatmap capture URLs, so it is not collecting new data. '
                : 'This page is not in your heatmap capture URLs. When capture limits take effect, it will stop collecting new data. '}
            Add it to your capture URLs, or switch to Allow all URLs.
        </LemonBanner>
    )
}

function MatchingDataReadiness(): JSX.Element {
    const { currentPageDataCheck, pageDataCheckLoading } = useValues(heatmapCreationLogic)
    const { requestPageDataCheck } = useActions(heatmapCreationLogic)

    if (pageDataCheckLoading) {
        return (
            <div className="flex items-center gap-2 text-muted">
                <Spinner /> Checking for interactions…
            </div>
        )
    }

    if (!currentPageDataCheck) {
        return (
            <div className="flex items-center gap-2 text-muted">
                <IconWarning className="size-5 shrink-0" />
                Choose a page to check for interactions.
            </div>
        )
    }

    if (currentPageDataCheck.outcome === 'detected') {
        return (
            <div className="flex items-center gap-2 text-secondary text-sm">
                <IconCheckCircle className="size-5 shrink-0" />
                <span>
                    {currentPageDataCheck.count?.toLocaleString()} interaction
                    {currentPageDataCheck.count === 1 ? '' : 's'} in the last 30 days
                </span>
            </div>
        )
    }

    const checkAgain = {
        children: 'Check again',
        onClick: () => requestPageDataCheck('manual'),
    }

    return (
        <LemonBanner type="warning" action={checkAgain}>
            {currentPageDataCheck.outcome === 'none'
                ? 'No interactions in the last 30 days. You can create this heatmap and collect data later.'
                : "Couldn't check for interactions. Try again or continue creating your heatmap."}
        </LemonBanner>
    )
}

function ChoosePageStep(): JSX.Element {
    const logic = heatmapLogic({ id: 'new' })
    const { displayUrl, isDisplayUrlValid, displayUrlIsPattern, dataUrl } = useValues(logic)
    const { setDisplayUrl } = useActions(logic)
    const { topUrls, topUrlsLoading, noPageviews } = useValues(heatmapsBrowserLogic)
    const { pageStepBlockReason } = useValues(heatmapCreationLogic)
    const { continueFromPage } = useActions(heatmapCreationLogic)

    return (
        <LemonCard hoverEffect={false} className="max-w-3xl w-full">
            <div className="flex flex-col gap-6">
                <div>
                    <h2 className="mb-1">Choose a page</h2>
                    <p className="text-muted mb-0">See where visitors click, move, and scroll on your website.</p>
                </div>
                <div>
                    <LemonLabel>Page URL</LemonLabel>
                    <LemonInputSelect
                        mode="single"
                        allowCustomValues
                        disableEditing
                        fullWidth
                        placeholder="https://www.example.com/pricing"
                        loading={topUrlsLoading}
                        value={displayUrl ? [displayUrl] : []}
                        onChange={(next) => setDisplayUrl(next[0] ?? '')}
                        options={(topUrls ?? []).map(({ url }) => ({
                            key: url,
                            label: url,
                            labelComponent: (
                                <span className="block min-w-0 max-w-full truncate ph-no-capture" title={url}>
                                    {url}
                                </span>
                            ),
                        }))}
                        title={topUrls?.length ? 'Most viewed pages' : undefined}
                        popoverClassName="max-w-0"
                        data-attr="heatmap-new-page-url"
                    />
                    {displayUrl && !isDisplayUrlValid ? (
                        displayUrlIsPattern ? (
                            <LemonBanner type="error" className="mt-2">
                                The page URL can't contain wildcards. Add wildcards to the heatmap data URL below.
                            </LemonBanner>
                        ) : (
                            <HeatmapsInvalidURL />
                        )
                    ) : null}
                    {!displayUrl && noPageviews && !topUrlsLoading ? (
                        <div className="text-xs text-muted mt-1">
                            No pageview events have been received yet. You can enter a URL manually.
                        </div>
                    ) : null}
                </div>

                <HeatmapAdvancedSettings
                    dataUrlPlaceholderFallback="https://www.example.com/*"
                    dataUrlHelp="Defaults to the page URL. Add * to combine data from multiple pages, for example https://www.example.com/users/*."
                    consentHelp={null}
                    showDataUrl
                    showConsent={false}
                    header="Combine data from multiple pages"
                />
                {dataUrl && pageStepBlockReason?.includes('heatmap data URL') ? (
                    <LemonBanner type="error">Enter a complete URL including http:// or https://.</LemonBanner>
                ) : null}

                <div className="flex flex-col gap-3 border-t pt-4" aria-live="polite">
                    <CaptureReadiness />
                    <CaptureUrlReadiness />
                    <MatchingDataReadiness />
                </div>
                <div className="flex justify-end">
                    <LemonButton
                        type="primary"
                        onClick={continueFromPage}
                        disabledReason={pageStepBlockReason}
                        data-attr="heatmap-creation-continue-page"
                    >
                        Continue
                    </LemonButton>
                </div>
            </div>
        </LemonCard>
    )
}

function PublicBackgroundChoice(): JSX.Element {
    const logic = heatmapLogic({ id: 'new' })
    const { type, displayUrl } = useValues(logic)
    const { setType } = useActions(logic)
    const { isDisplayUrlAuthorized, authorizationDisabledReason, preflightMessage } = useValues(heatmapCreationLogic)
    const { authorizeDisplayUrl } = useActions(heatmapCreationLogic)
    const { currentTeamLoading } = useValues(teamLogic)

    return (
        <div className="flex flex-col gap-4">
            <div>
                <LemonLabel>Display page as</LemonLabel>
                <LemonSegmentedButton
                    options={[
                        {
                            label: 'Screenshot',
                            value: 'screenshot',
                            icon: <IconImage />,
                            'data-attr': 'heatmap-background-screenshot',
                        },
                        {
                            label: 'Live page',
                            value: 'iframe',
                            icon: <IconBrowser />,
                            'data-attr': 'heatmap-background-iframe',
                        },
                    ]}
                    value={type}
                    onChange={(value: HeatmapType) => setType(value)}
                    size="small"
                />
                <p className="text-muted text-sm mt-2 mb-0">
                    {type === 'screenshot'
                        ? 'Capture the full page as a static background.'
                        : 'Load your website directly. The page must allow embedding.'}
                </p>
            </div>

            {type === 'iframe' && !isDisplayUrlAuthorized ? (
                <LemonBanner type="warning">
                    <div className="flex flex-col gap-3">
                        <div>
                            The page URL's origin must be authorized before PostHog can embed it. Screenshot does not
                            require authorization.
                        </div>
                        {authorizationDisabledReason ? (
                            <div className="text-sm">
                                Ask a web analytics editor to authorize this URL, or choose Screenshot.
                            </div>
                        ) : (
                            <LemonButton
                                type="secondary"
                                size="small"
                                className="w-fit"
                                onClick={authorizeDisplayUrl}
                                loading={currentTeamLoading}
                                data-attr="heatmap-authorize-display-url"
                            >
                                Authorize this URL
                            </LemonButton>
                        )}
                    </div>
                </LemonBanner>
            ) : null}

            {type === 'iframe' && preflightMessage ? (
                <LemonBanner
                    type="error"
                    action={{ children: 'Switch to screenshot', onClick: () => setType('screenshot') }}
                >
                    {preflightMessage}
                </LemonBanner>
            ) : null}

            {type === 'screenshot' ? (
                <LemonCollapse
                    panels={[
                        {
                            key: 'screenshot-options',
                            header: 'Screenshot options',
                            content: (
                                <div className="flex flex-col gap-4">
                                    <HeatmapPageFields
                                        dataUrlPlaceholderFallback=""
                                        dataUrlHelp={null}
                                        consentHelp="Close cookie and consent banners before capturing. This may take longer."
                                        showDataUrl={false}
                                        showConsent
                                    />
                                    <HeatmapScreenshotAccessNotice url={displayUrl} />
                                </div>
                            ),
                        },
                    ]}
                />
            ) : null}
        </div>
    )
}

function ChooseBackgroundStep(): JSX.Element {
    const logic = heatmapLogic({ id: 'new' })
    const { displayUrl } = useValues(logic)
    const { pageAccess, backgroundStepBlockReason, recordingBackgroundData } = useValues(heatmapCreationLogic)
    const { setPageAccess, continueFromBackground, goBack, markRecordingHandoff, navigateToStep } =
        useActions(heatmapCreationLogic)

    return (
        <LemonCard hoverEffect={false} className="max-w-3xl w-full">
            <div className="flex flex-col gap-6">
                <div>
                    <h2 className="mb-1">Choose a background</h2>
                    <p className="text-muted mb-0">Choose how to display the page beneath your heatmap.</p>
                </div>

                <div>
                    <LemonLabel>Page access</LemonLabel>
                    <LemonSegmentedButton
                        options={[
                            { label: 'Public page', value: 'public', 'data-attr': 'heatmap-page-access-public' },
                            { label: 'Requires login', value: 'login', 'data-attr': 'heatmap-page-access-login' },
                        ]}
                        value={pageAccess ?? undefined}
                        onChange={setPageAccess}
                        size="small"
                    />
                </div>

                {pageAccess === 'public' ? <PublicBackgroundChoice /> : null}
                {pageAccess === 'login' && displayUrl ? (
                    <div className="flex flex-col gap-4">
                        <div className="flex flex-wrap items-center justify-between gap-3 border-b pb-4">
                            <div className="flex-1 min-w-48">
                                <h3 className="mb-1">Capture from your browser</h3>
                                <p className="text-muted text-sm mb-0">
                                    Save the signed-in page using the toolbar's “Save to PostHog” action.
                                </p>
                            </div>
                            <LemonButton
                                type="secondary"
                                icon={<IconBrowser />}
                                to={appEditorUrl(displayUrl, { userIntent: 'heatmaps' })}
                                targetBlank
                                data-attr="heatmap-creation-toolbar-capture"
                            >
                                Open in toolbar
                            </LemonButton>
                        </div>
                        <div>
                            <h3 className="mb-1">Use a session recording</h3>
                            <p className="text-muted text-sm mb-0">
                                Choose a recorded moment for a temporary heatmap. Recording backgrounds aren't saved.
                            </p>
                        </div>
                        <HeatmapRecordingFallback
                            url={displayUrl}
                            showEmptyState
                            guidedSelection
                            onRecordingHandoff={markRecordingHandoff}
                        />
                    </div>
                ) : null}

                <div className="flex flex-wrap justify-between gap-2 border-t pt-4">
                    <LemonButton type="secondary" onClick={goBack}>
                        Back
                    </LemonButton>
                    {pageAccess !== 'login' ? (
                        <LemonButton
                            type="primary"
                            onClick={continueFromBackground}
                            disabledReason={backgroundStepBlockReason}
                            data-attr="heatmap-creation-continue-background"
                        >
                            Continue
                        </LemonButton>
                    ) : recordingBackgroundData ? (
                        <LemonButton type="primary" onClick={() => navigateToStep('review')}>
                            Continue
                        </LemonButton>
                    ) : null}
                </div>
            </div>
        </LemonCard>
    )
}

function ReviewStatus({ warning, children }: { warning?: boolean; children: React.ReactNode }): JSX.Element {
    return (
        <div className={cn('flex items-center gap-2 text-sm', warning ? 'text-warning' : 'text-secondary')}>
            {warning ? <IconWarning className="size-5 shrink-0" /> : <IconCheckCircle className="size-5 shrink-0" />}
            <span>{children}</span>
        </div>
    )
}

function RecordingBackgroundPreview({
    html,
    width,
    height,
}: {
    html: string
    width: number
    height: number
}): JSX.Element {
    const { ref, width: containerWidth = 0 } = useResizeObserver<HTMLDivElement>()
    const hasDims = width > 0 && height > 0
    const measured = containerWidth > 0
    // Scale the natural-size snapshot down to fit the container so the whole recorded viewport is
    // visible; never scale up past its natural size (a narrow/mobile capture stays crisp).
    const scale = hasDims && measured ? Math.min(1, containerWidth / width) : 1

    return (
        <div ref={ref} className="overflow-hidden rounded border bg-surface-secondary w-full">
            {hasDims ? (
                measured ? (
                    // eslint-disable-next-line react/forbid-dom-props
                    <div className="relative" style={{ height: height * scale }}>
                        <iframe
                            srcDoc={html}
                            title="Selected session recording background"
                            sandbox="allow-same-origin"
                            tabIndex={-1}
                            className="absolute top-0 left-0 origin-top-left border-0 bg-white pointer-events-none ph-no-capture"
                            // eslint-disable-next-line react/forbid-dom-props
                            style={{ width, height, transform: `scale(${scale})` }}
                        />
                    </div>
                ) : (
                    // Reserve the recording's aspect ratio until the observer reports a width, so a wide
                    // capture never renders at full size and gets clipped before we can scale it down.
                    // eslint-disable-next-line react/forbid-dom-props
                    <div className="w-full" style={{ aspectRatio: `${width} / ${height}` }} />
                )
            ) : (
                <iframe
                    srcDoc={html}
                    title="Selected session recording background"
                    sandbox="allow-same-origin"
                    tabIndex={-1}
                    className="w-full h-96 border-0 bg-white pointer-events-none ph-no-capture"
                />
            )}
        </div>
    )
}

function ReviewStep(): JSX.Element {
    const logic = heatmapLogic({ id: 'new' })
    const { displayUrl, type, loading } = useValues(logic)
    const { createHeatmap } = useActions(logic)
    const {
        captureEnabled,
        hasMatchingData,
        creationContext,
        reviewBlockReason,
        pageAccess,
        recordingBackgroundData,
        effectiveDataUrl,
    } = useValues(heatmapCreationLogic)
    const { goBack, openRecordingHeatmap } = useActions(heatmapCreationLogic)
    const usesRecordingBackground = pageAccess === 'login' && !!recordingBackgroundData

    return (
        <LemonCard hoverEffect={false} className={cn('w-full', usesRecordingBackground ? 'max-w-5xl' : 'max-w-3xl')}>
            <div className="flex flex-col gap-6">
                <div>
                    <h2 className="mb-1">{usesRecordingBackground ? 'Review background' : 'Review and create'}</h2>
                    <p className="text-muted mb-0">
                        {usesRecordingBackground
                            ? 'Confirm the page state you selected before opening the heatmap.'
                            : 'Your heatmap will show interactions as data arrives.'}
                    </p>
                </div>

                <dl className="grid grid-cols-1 @min-[32rem]/main-content:grid-cols-[8rem_minmax(0,1fr)] gap-x-4 gap-y-2 mb-0">
                    <dt className="text-muted">Page</dt>
                    <dd className="ph-no-capture break-all">{displayUrl}</dd>
                    <dt className="text-muted">Heatmap data</dt>
                    <dd>
                        <span className="font-medium">
                            {hasWildcard(effectiveDataUrl ?? '') ? 'Pattern' : 'Exact URL'}:
                        </span>{' '}
                        <span className="ph-no-capture break-all">{effectiveDataUrl}</span>
                    </dd>
                    <dt className="text-muted">Background</dt>
                    <dd>
                        {usesRecordingBackground
                            ? 'Session recording'
                            : type === 'screenshot'
                              ? 'Screenshot'
                              : 'Live page'}
                    </dd>
                </dl>

                {recordingBackgroundData ? (
                    <RecordingBackgroundPreview
                        html={recordingBackgroundData.html}
                        width={recordingBackgroundData.width}
                        height={recordingBackgroundData.height}
                    />
                ) : null}

                <div className="flex flex-col gap-2 border-t pt-4">
                    <ReviewStatus warning={!captureEnabled}>
                        {captureEnabled ? 'Heatmap capture is enabled.' : 'Heatmap capture is disabled.'}
                    </ReviewStatus>
                    <ReviewStatus warning={hasMatchingData !== true}>
                        {hasMatchingData === true
                            ? 'Matching data was found in the last 30 days.'
                            : hasMatchingData === false
                              ? 'No matching data was found in the last 30 days.'
                              : 'Matching data could not be confirmed.'}
                    </ReviewStatus>
                </div>

                <div className="flex flex-wrap justify-between gap-2 border-t pt-4">
                    <LemonButton type="secondary" onClick={goBack} disabled={!usesRecordingBackground && loading}>
                        Back
                    </LemonButton>
                    {usesRecordingBackground ? (
                        <LemonButton
                            type="primary"
                            onClick={openRecordingHeatmap}
                            disabledReason={reviewBlockReason}
                            data-attr="open-recording-heatmap"
                        >
                            View heatmap
                        </LemonButton>
                    ) : (
                        <AccessControlAction
                            resourceType={AccessControlResourceType.Heatmap}
                            minAccessLevel={AccessControlLevel.Editor}
                        >
                            <LemonButton
                                type="primary"
                                onClick={() => createHeatmap(creationContext)}
                                loading={loading}
                                disabledReason={reviewBlockReason}
                                data-attr="save-heatmap"
                            >
                                Create heatmap
                            </LemonButton>
                        </AccessControlAction>
                    )}
                </div>
            </div>
        </LemonCard>
    )
}

function RecordingHeatmapStep(): JSX.Element {
    const { closeRecordingHeatmap, finishRecordingHeatmap } = useActions(heatmapCreationLogic)

    return (
        <div className="flex flex-col gap-4">
            <LemonCard hoverEffect={false} className="sticky top-0 z-20">
                <div className="flex flex-wrap items-center justify-between gap-4">
                    <div>
                        <h2 className="mb-1">Explore your heatmap</h2>
                        <p className="text-muted mb-0">
                            This heatmap uses your selected recording moment and isn't saved.
                        </p>
                    </div>
                    <div className="flex flex-wrap gap-2">
                        <LemonButton type="secondary" onClick={closeRecordingHeatmap}>
                            Back to review
                        </LemonButton>
                        <LemonButton type="primary" onClick={finishRecordingHeatmap}>
                            Finish
                        </LemonButton>
                    </div>
                </div>
            </LemonCard>
            <HeatmapRecording embedded />
        </div>
    )
}

export function HeatmapNewScene(): JSX.Element {
    const { featureFlags } = useValues(featureFlagLogic)

    return featureFlags[FEATURE_FLAGS.HEATMAPS_CREATION_FLOW] ? <HeatmapCreationWizard /> : <HeatmapNewSceneLegacy />
}

function HeatmapCreationWizard(): JSX.Element {
    const logic = heatmapLogic({ id: 'new' })
    const { name } = useValues(logic)
    const { setName } = useActions(logic)
    const { currentStep, recordingHeatmapOpen } = useValues(heatmapCreationLogic)

    return (
        <SceneContent>
            <SceneTitleSection
                name={name}
                resourceType={{ type: 'heatmap' }}
                description={null}
                canEdit
                forceEdit
                onNameChange={setName}
                forceBackTo={{ name: 'Heatmaps', path: urls.heatmaps(), key: 'heatmaps' }}
            />
            <HeatmapsPricingNotice />
            <HeatmapCreationStepper />
            {currentStep === 'page' ? <ChoosePageStep /> : null}
            {currentStep === 'background' ? <ChooseBackgroundStep /> : null}
            {currentStep === 'review' ? recordingHeatmapOpen ? <RecordingHeatmapStep /> : <ReviewStep /> : null}
        </SceneContent>
    )
}
