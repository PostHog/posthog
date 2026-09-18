import { BindLogic, useActions, useAsyncActions, useValues } from 'kea'
import { useRef } from 'react'
import useResizeObserver from 'use-resize-observer'

import * as directorPng from '@posthog/brand/hoggies/png/director'
import { IconBrowser, IconDownload } from '@posthog/icons'
import { Spinner, Tooltip } from '@posthog/lemon-ui'

import { pngHoggie } from 'lib/brand/hoggies'
import { appEditorUrl } from 'lib/components/AuthorizedUrlList/authorizedUrlListLogic'
import { HeatmapCanvas } from 'lib/components/heatmaps/HeatmapCanvas'
import { MAX_HEATMAP_HEIGHT } from 'lib/components/heatmaps/heatmapDataLogic'
import { LemonBanner } from 'lib/lemon-ui/LemonBanner/LemonBanner'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LoadingBar } from 'lib/lemon-ui/LoadingBar'
import { getAccessControlDisabledReason } from 'lib/utils/accessControlUtils'
import { SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'
import { AccessControlLevel, AccessControlResourceType } from '~/types'

import { FilterPanel } from '../../components/FilterPanel'
import { HeatmapHeader } from '../../components/HeatmapHeader'
import { HeatmapRecordingFallback } from '../../components/HeatmapRecordingFallback'
import { heatmapLogic } from './heatmapLogic'

const HedgehogDirector = pngHoggie(directorPng)

export const scene: SceneExport<{ id: string }> = {
    component: HeatmapScene,
    logic: heatmapLogic,
    paramsToProps: ({ params: { id } }) => ({ id }),
}

export function HeatmapScene({ id }: { id: string }): JSX.Element {
    const logicProps = { id: id }
    const logic = heatmapLogic(logicProps)

    const {
        name,
        loading,
        displayUrl,
        widthOverride,
        heightOverride,
        screenshotUrl,
        generatingScreenshot,
        screenshotLoaded,
        containerWidth,
        desiredNumericWidth,
        effectiveWidth,
        scalePercent,
        isHeightCapped,
        lockedWidth,
        hasUnsavedChanges,
        saving,
        saveDisabledReason,
        editDisabledReason,
        previewType,
        previewVersion,
        previewError,
        previewUnavailable,
        regenerateDisabledReason,
        switchToScreenshotDisabledReason,
        displayUrlIsPattern,
    } = useValues(logic)
    const {
        setName,
        onIframeLoad,
        setScreenshotLoaded,
        setScreenshotError,
        exportHeatmap,
        setContainerWidth,
        discardChanges,
        regenerateScreenshot,
        switchToScreenshot,
    } = useActions(logic)
    const { updateHeatmap } = useAsyncActions(logic)

    const toolbarAccessDisabledReason = getAccessControlDisabledReason(
        AccessControlResourceType.Toolbar,
        AccessControlLevel.Viewer
    )

    const { ref: measureRef } = useResizeObserver<HTMLDivElement>({
        onResize: ({ width }) => setContainerWidth(width ?? null),
    })
    const exportRef = useRef<HTMLButtonElement | null>(null)
    const focusExport = (): void => exportRef.current?.focus({ preventScroll: true })
    const saveAndRefocus = async (): Promise<void> => {
        await updateHeatmap()
        if (!logic.values.hasUnsavedChanges) {
            focusExport()
        }
    }
    const previewRecovery =
        previewType === 'screenshot'
            ? {
                  title: "Screenshot couldn't load",
                  label: 'Retry screenshot',
                  onClick: regenerateScreenshot,
                  disabledReason: regenerateDisabledReason,
              }
            : {
                  title: "This page couldn't load in the preview",
                  label: 'Switch to screenshot',
                  onClick: switchToScreenshot,
                  disabledReason: switchToScreenshotDisabledReason,
              }

    if (loading) {
        return (
            <SceneContent>
                <Spinner />
            </SceneContent>
        )
    }

    return (
        <BindLogic logic={heatmapLogic} props={logicProps}>
            <SceneContent>
                <SceneTitleSection
                    name={name}
                    resourceType={{
                        type: 'heatmap',
                    }}
                    description={null}
                    canEdit={!editDisabledReason}
                    onNameChange={setName}
                    forceBackTo={{
                        name: 'Heatmaps',
                        path: urls.heatmaps(),
                        key: 'heatmaps',
                    }}
                    actions={
                        <>
                            {(hasUnsavedChanges || saving) && !editDisabledReason && (
                                <>
                                    <LemonButton
                                        type="secondary"
                                        onClick={() => {
                                            discardChanges()
                                            focusExport()
                                        }}
                                        disabledReason={saving ? 'Saving changes' : null}
                                        size="small"
                                        data-attr="heatmap-discard-changes"
                                    >
                                        Discard changes
                                    </LemonButton>
                                    <LemonButton
                                        type="primary"
                                        onClick={() => void saveAndRefocus()}
                                        loading={saving}
                                        disabledReason={saveDisabledReason}
                                        size="small"
                                        data-attr="heatmap-save"
                                    >
                                        {saving ? 'Saving…' : 'Save'}
                                    </LemonButton>
                                </>
                            )}
                            <LemonButton
                                type="tertiary"
                                size="small"
                                to={displayUrl ? appEditorUrl(displayUrl, { userIntent: 'heatmaps' }) : undefined}
                                targetBlank
                                data-attr="heatmaps-open-in-toolbar"
                                disabledReason={!displayUrl ? 'Select a URL first' : toolbarAccessDisabledReason}
                                tooltip="Explore heatmaps on your website, including pages that require a login"
                            >
                                Open in toolbar
                            </LemonButton>
                            <LemonButton
                                ref={exportRef}
                                onClick={exportHeatmap}
                                data-attr="export-heatmap"
                                type="secondary"
                                icon={<IconDownload />}
                                size="small"
                                tooltip="Export heatmap as PNG"
                                tooltipPlacement="bottom"
                                disabledReason={
                                    previewType === 'screenshot' &&
                                    (!screenshotUrl || !screenshotLoaded || generatingScreenshot)
                                        ? 'Screenshot is not ready'
                                        : undefined
                                }
                            >
                                Export
                            </LemonButton>
                        </>
                    }
                />
                <HeatmapHeader />
                <FilterPanel lockedWidth={lockedWidth ?? undefined} previewUnavailable={previewUnavailable} />
                {isHeightCapped && (
                    <LemonBanner type="info" className="mb-2">
                        This heatmap is capped at {MAX_HEATMAP_HEIGHT.toLocaleString()}px tall to keep rendering fast,
                        so data below that point isn't shown.
                    </LemonBanner>
                )}
                <div ref={measureRef} className="w-full">
                    <div
                        className="border mx-auto bg-surface-primary rounded-lg"
                        style={{ width: effectiveWidth ?? '100%' }}
                    >
                        <div className="p-2 border-b text-muted-foreground gap-2 flex flex-wrap items-center">
                            <IconBrowser />{' '}
                            <span className="min-w-0 flex-1 truncate" title={displayUrl ?? undefined}>
                                {displayUrl}
                            </span>
                            {typeof widthOverride === 'number' && containerWidth && widthOverride > containerWidth ? (
                                <Tooltip
                                    title={`Scaled from ${widthOverride}px to ${Math.round(effectiveWidth as number)}px to fit the preview`}
                                >
                                    <span className="text-xs text-muted">{scalePercent}%</span>
                                </Tooltip>
                            ) : null}
                        </div>
                        {previewError ? (
                            <div
                                className="min-h-80 flex flex-col items-center justify-center gap-3 p-6 text-center"
                                data-attr="heatmap-preview-error"
                            >
                                <IconBrowser className="text-3xl text-muted" />
                                <h3 className="mb-0">{previewRecovery.title}</h3>
                                <p className="text-muted max-w-lg mb-0">{previewError}</p>
                                <LemonButton
                                    type="primary"
                                    onClick={previewRecovery.onClick}
                                    loading={generatingScreenshot || saving}
                                    disabledReason={previewRecovery.disabledReason}
                                    data-attr="heatmap-preview-recovery"
                                >
                                    {previewRecovery.label}
                                </LemonButton>
                                {displayUrl && !displayUrlIsPattern && <HeatmapRecordingFallback url={displayUrl} />}
                            </div>
                        ) : previewType === 'screenshot' ? (
                            <div className="relative flex w-full justify-center flex-1" style={{ width: '100%' }}>
                                {generatingScreenshot ? (
                                    <div
                                        className="flex-1 flex items-center justify-center min-h-96"
                                        data-attr="heatmap-generating-screenshot"
                                    >
                                        <style>{`@keyframes hog-wobble{from{transform:rotate(0deg)}to{transform:rotate(5deg)}}`}</style>
                                        <div className="text-sm text-center font-semibold">
                                            <HedgehogDirector
                                                className="w-32 h-32 mx-auto mb-2"
                                                style={{
                                                    animation: 'hog-wobble 1.2s ease-in-out infinite alternate',
                                                    transformOrigin: '50% 50%',
                                                }}
                                            />
                                            Generating screenshot…
                                            <div className="text-muted text-xs mt-2">
                                                This usually takes a few minutes
                                            </div>
                                            <LoadingBar />
                                        </div>
                                    </div>
                                ) : screenshotUrl ? (
                                    <>
                                        {screenshotLoaded && (
                                            <HeatmapCanvas
                                                key={effectiveWidth ?? 'auto'}
                                                positioning="absolute"
                                                widthOverride={desiredNumericWidth ?? undefined}
                                                context="in-app"
                                            />
                                        )}
                                        <img
                                            id="heatmap-screenshot"
                                            src={screenshotUrl}
                                            alt="Website screenshot for heatmap analysis"
                                            style={{
                                                width: '100%',
                                                height: 'auto',
                                                display: 'block',
                                            }}
                                            onLoad={() => {
                                                setScreenshotLoaded(true)
                                                setScreenshotError(null)
                                            }}
                                            className="rounded-b-lg border-l border-r border-b"
                                            onError={() => {
                                                setScreenshotLoaded(false)
                                                setScreenshotError('The screenshot failed to load.')
                                            }}
                                        />
                                    </>
                                ) : null}
                            </div>
                        ) : (
                            <div
                                className="relative"
                                // eslint-disable-next-line react/forbid-dom-props
                                style={{ height: heightOverride }}
                            >
                                <HeatmapCanvas
                                    positioning="absolute"
                                    widthOverride={desiredNumericWidth ?? undefined}
                                    context="in-app"
                                />
                                <iframe
                                    key={previewVersion}
                                    id="heatmap-iframe"
                                    title="Heatmap browser"
                                    className="bg-white rounded-b-lg"
                                    // eslint-disable-next-line react/forbid-dom-props
                                    style={{ width: '100%', height: heightOverride }}
                                    src={displayUrl || ''}
                                    onLoad={onIframeLoad}
                                    // these two sandbox values are necessary so that the site and toolbar can run
                                    // this is a very loose sandbox,
                                    // but we specify it so that at least other capabilities are denied
                                    sandbox="allow-scripts allow-same-origin"
                                    // we don't allow things such as camera access though
                                    allow=""
                                />
                            </div>
                        )}
                    </div>
                </div>
            </SceneContent>
        </BindLogic>
    )
}
