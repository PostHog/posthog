import '../ErrorTrackingIssueScene/ErrorTrackingIssueScene.scss'

import clsx from 'clsx'
import { BindLogic, useActions, useValues } from 'kea'
import posthog from 'posthog-js'
import { useEffect, useRef } from 'react'

import { IconRewindPlay, IconX } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { NotFound } from 'lib/components/NotFound'
import { Resizer } from 'lib/components/Resizer/Resizer'
import { ResizerLogicProps, resizerLogic } from 'lib/components/Resizer/resizerLogic'
import { SceneMenuBarFileItems } from 'lib/components/Scenes/SceneMenuBarFileItems'
import ViewRecordingsPlaylistButton from 'lib/components/ViewRecordingButton/ViewRecordingsPlaylistButton'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { useWindowSize } from 'lib/hooks/useWindowSize'
import { newInternalTab } from 'lib/utils/newInternalTab'
import { SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { SceneMenuBar, SceneMenuBarItem, SceneMenuBarMenu } from '~/layout/scenes/components/SceneMenuBar'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'
import { ReplayTabs } from '~/types'

import { useAttachedContext } from 'products/posthog_ai/frontend/api/logics'

import { PostHogSDKIssueBanner } from '../../components/Banners/PostHogSDKIssueBanner'
import { miniBreakdownsLogic } from '../../components/Breakdowns/miniBreakdownsLogic'
import { getEventMarkerColor } from '../../components/EventsTable/EventsTable'
import { ExceptionCard } from '../../components/ExceptionCard'
import { StackTraceActions } from '../../components/ExceptionCard/Tabs/StackTraceTab/StackTraceActions'
import { StatusIndicator } from '../../components/Indicators'
import { issueActionsLogic } from '../../components/IssueActions/issueActionsLogic'
import {
    ERROR_TRACKING_ISSUE_SCENE_LOGIC_KEY,
    issueFiltersLogic,
} from '../../components/IssueFilters/issueFiltersLogic'
import { IssueSeveritySelect } from '../../components/IssueSeveritySelect'
import { IssueStatusButton } from '../../components/IssueStatusButton'
import { ErrorTrackingSetupPrompt } from '../../components/SetupPrompt/SetupPrompt'
import { StyleVariables } from '../../components/StyleVariables'
import { useErrorTagRenderer } from '../../hooks/use-error-tag-renderer'
import { getIssueReplayDateRange, getIssueReplayFilterGroup } from '../../utils'
import { ErrorTrackingIssueSceneLogicProps, errorTrackingIssueSceneLogic } from './errorTrackingIssueSceneLogic'
import { IssueEventsPanel } from './IssueEventsPanel'
import { LinkedReports } from './LinkedReports'
import { ErrorTrackingIssueScenePanel } from './ScenePanel'
import { IssueAssigneeSelect } from './ScenePanel/IssueAssigneeSelect'

export const scene: SceneExport<ErrorTrackingIssueSceneLogicProps> = {
    component: ErrorTrackingIssueScene,
    logic: errorTrackingIssueSceneLogic,
    paramsToProps: ({ params: { id }, searchParams: { fingerprint, timestamp } }) => ({ id, fingerprint, timestamp }),
}

export function ErrorTrackingIssueScene(): JSX.Element {
    const { issue, issueId, issueIdValid, lastSeen, initialEventTimestamp, selectedEvent, mobileDetailOpen } =
        useValues(errorTrackingIssueSceneLogic)
    const { updateAssignee, updateSeverity, updateStatus, updateName, setMobileDetailOpen } =
        useActions(errorTrackingIssueSceneLogic)
    const { severityUpdateInFlightIds } = useValues(issueActionsLogic)
    const { isWindowLessThan } = useWindowSize()
    const isMobile = isWindowLessThan('md')
    const sceneMenuBarEnabled = useFeatureFlag('SCENE_MENU_BAR')
    const hasIssueSplitting = useFeatureFlag('ERROR_TRACKING_ISSUE_SPLITTING')
    const hasSeverityRules = useFeatureFlag('ERROR_TRACKING_SEVERITY_RULES')

    useAttachedContext(
        issueIdValid ? [{ type: 'error_tracking_issue', key: issueId, label: issue?.name ?? undefined }] : null
    )

    useEffect(() => {
        if (!issueIdValid) {
            return
        }
        const utmSource = new URLSearchParams(window.location.search).get('utm_source')
        posthog.capture('error_tracking_issue_viewed', {
            issue_id: issueId,
            ...(utmSource ? { utm_source: utmSource } : {}),
        })
    }, [issueId, issueIdValid])

    if (!issueIdValid) {
        return <NotFound object="issue" />
    }

    return (
        <StyleVariables>
            <ErrorTrackingSetupPrompt>
                <BindLogic logic={issueFiltersLogic} props={{ logicKey: ERROR_TRACKING_ISSUE_SCENE_LOGIC_KEY }}>
                    <BindLogic logic={miniBreakdownsLogic} props={{ issueId }}>
                        {issue && (
                            <div className="flex flex-col h-[calc(var(--scene-layout-rect-height))]">
                                {sceneMenuBarEnabled && (
                                    <SceneMenuBar>
                                        <SceneMenuBarMenu label="File" dataAttr="issue-menubar-file">
                                            <SceneMenuBarFileItems dataAttrKey="issue" />
                                            {hasIssueSplitting && (
                                                <SceneMenuBarItem
                                                    onClick={() =>
                                                        window.open(
                                                            urls.errorTrackingIssueFingerprints(issue.id),
                                                            '_self'
                                                        )
                                                    }
                                                    data-attr="issue-menubar-fingerprints"
                                                >
                                                    Manage fingerprints
                                                </SceneMenuBarItem>
                                            )}
                                        </SceneMenuBarMenu>
                                        <SceneMenuBarMenu label="View" dataAttr="issue-menubar-view">
                                            <SceneMenuBarItem
                                                onClick={() => {
                                                    const url = urls.replay(ReplayTabs.Home, {
                                                        ...getIssueReplayDateRange(
                                                            issue.first_seen,
                                                            lastSeen,
                                                            selectedEvent?.timestamp ?? initialEventTimestamp
                                                        ),
                                                        filter_group: getIssueReplayFilterGroup(issue.id),
                                                    })
                                                    newInternalTab(url)
                                                }}
                                                data-attr="issue-menubar-view-recordings"
                                            >
                                                <IconRewindPlay />
                                                View recordings
                                            </SceneMenuBarItem>
                                        </SceneMenuBarMenu>
                                    </SceneMenuBar>
                                )}
                                <SceneTitleSection
                                    canEdit
                                    name={issue.name ?? undefined}
                                    onNameChange={updateName}
                                    description={null}
                                    resourceType={{ type: 'error_tracking' }}
                                    className={clsx(
                                        'pl-4 pr-2 h-[50px] @2xl/main-content:relative top-[0px] mt-0 mx-0 mb-0',
                                        isMobile
                                            ? '[&>.scene-title-section]:flex-row [&>.scene-title-section]:items-center [&>.scene-title-section>*:last-child]:order-last'
                                            : undefined
                                    )}
                                    actions={
                                        isMobile ? undefined : (
                                            <div className="flex items-center gap-1">
                                                <StatusIndicator status={issue.status} withTooltip />
                                                {hasSeverityRules ? (
                                                    <IssueSeveritySelect
                                                        severity={issue.severity}
                                                        onChange={updateSeverity}
                                                        loading={severityUpdateInFlightIds.includes(issue.id)}
                                                    />
                                                ) : null}
                                                <IssueAssigneeSelect
                                                    assignee={issue.assignee}
                                                    onChange={updateAssignee}
                                                    disabled={issue.status != 'active'}
                                                />
                                                <ViewRecordingsPlaylistButton
                                                    filters={{
                                                        ...getIssueReplayDateRange(
                                                            issue.first_seen,
                                                            lastSeen,
                                                            selectedEvent?.timestamp ?? initialEventTimestamp
                                                        ),
                                                        filter_group: getIssueReplayFilterGroup(issue.id),
                                                    }}
                                                    size="small"
                                                    type="secondary"
                                                    data-attr="error-tracking-issue-view-recordings"
                                                />
                                                <IssueStatusButton status={issue.status} onChange={updateStatus} />
                                            </div>
                                        )
                                    }
                                />

                                {isMobile && (
                                    <div className="flex items-center gap-1.5 px-2 py-1.5 border-b flex-wrap">
                                        <StatusIndicator status={issue.status} withTooltip />
                                        {hasSeverityRules ? (
                                            <IssueSeveritySelect
                                                severity={issue.severity}
                                                onChange={updateSeverity}
                                                loading={severityUpdateInFlightIds.includes(issue.id)}
                                            />
                                        ) : null}
                                        <IssueAssigneeSelect
                                            assignee={issue.assignee}
                                            onChange={updateAssignee}
                                            disabled={issue.status != 'active'}
                                        />
                                        <IssueStatusButton status={issue.status} onChange={updateStatus} />
                                        {!mobileDetailOpen && (
                                            <LemonButton
                                                size="small"
                                                type="secondary"
                                                onClick={() => setMobileDetailOpen(true)}
                                            >
                                                Details
                                            </LemonButton>
                                        )}
                                    </div>
                                )}

                                <ErrorTrackingIssueScenePanel issue={issue} />

                                <div className="ErrorTrackingIssue flex flex-grow min-h-0 overflow-hidden">
                                    <div className="relative flex flex-1 h-full w-full min-h-0">
                                        <LeftHandColumn isMobile={isMobile} />
                                        <RightHandColumn
                                            isMobile={isMobile}
                                            isOpen={mobileDetailOpen}
                                            onClose={() => setMobileDetailOpen(false)}
                                        />
                                    </div>
                                </div>
                            </div>
                        )}
                    </BindLogic>
                </BindLogic>
            </ErrorTrackingSetupPrompt>
        </StyleVariables>
    )
}

const RightHandColumn = ({
    isMobile,
    isOpen,
    onClose,
}: {
    isMobile: boolean
    isOpen: boolean
    onClose: () => void
}): JSX.Element | null => {
    const { issue, issueLoading, selectedEvent, initialEvent, initialEventLoading, summary } =
        useValues(errorTrackingIssueSceneLogic)
    const tagRenderer = useErrorTagRenderer()
    const detailEvent = selectedEvent ?? initialEvent

    if (isMobile && !isOpen) {
        return null
    }

    return (
        <div
            className={clsx(
                // No gap between the pane's sections: each one ends in a border, and a gap would show
                // the page behind the pane as a band next to that border.
                'flex flex-col flex-1 min-h-0',
                isMobile ? 'absolute inset-0 z-20 bg-surface-primary' : 'min-w-[375px]'
            )}
        >
            {isMobile && (
                <div className="flex shrink-0 justify-end p-1">
                    <LemonButton icon={<IconX />} size="small" onClick={onClose} aria-label="Close detail" />
                </div>
            )}
            <PostHogSDKIssueBanner event={detailEvent} />
            <LinkedReports />
            <div className="flex-1 min-h-0 flex flex-col">
                <ExceptionCard
                    issueId={issue?.id ?? 'no-issue'}
                    issueName={issue?.name ?? null}
                    loading={issueLoading || initialEventLoading}
                    event={detailEvent ?? undefined}
                    eventMarkerColor={
                        detailEvent
                            ? getEventMarkerColor(detailEvent.uuid, summary?.first_event_uuid, summary?.last_event_uuid)
                            : undefined
                    }
                    label={tagRenderer(detailEvent)}
                    renderStackTraceActions={() => {
                        return issue ? <StackTraceActions issue={issue} /> : null
                    }}
                />
            </div>
        </div>
    )
}

const LeftHandColumn = ({ isMobile }: { isMobile: boolean }): JSX.Element => {
    const ref = useRef<HTMLDivElement>(null)
    const resizerLogicProps: ResizerLogicProps = {
        containerRef: ref,
        logicKey: 'error-tracking-issue',
        persistent: true,
        placement: 'right',
        persistPrefix: 'error-tracking-issue-view-columns-ratio',
    }
    const { desiredSize } = useValues(resizerLogic(resizerLogicProps))

    return (
        <div
            ref={ref}
            // eslint-disable-next-line react/forbid-dom-props
            style={
                isMobile
                    ? undefined
                    : {
                          width: desiredSize ?? '40%',
                          minWidth: 320,
                      }
            }
            className={clsx('flex flex-col h-full relative bg-surface-primary', isMobile && 'flex-1 max-w-full')}
        >
            <IssueEventsPanel />

            {!isMobile && <Resizer {...resizerLogicProps} />}
        </div>
    )
}
