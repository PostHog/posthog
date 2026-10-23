import type { Meta, StoryFn } from '@storybook/react'
import { BindLogic, useActions, useValues } from 'kea'
import { useEffect } from 'react'

import { SpinnerOverlay } from '@posthog/lemon-ui'

import { FEATURE_FLAGS } from 'lib/constants'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'

import { workflowLogic } from '../../../workflowLogic'
import { HogFlowEditor } from '../../HogFlowEditor'
import type { HogFlowEditorActionMetrics } from '../../hogFlowEditorLogic'
import { createWorkflowEditorStoryDecorator } from '../workflowEditorStoryFixtures'
import { tileCanvasLogic } from './tileCanvasLogic'
import {
    AI_SUPPORT_TRIAGE,
    LONG_EMAILS,
    TICKET_TO_SLACK,
    TILE_CANVAS_WORKFLOWS,
    TRIAL_TO_PAID,
    TRIAL_TO_PAID_METRICS,
} from './tileCanvasStoryFixtures'

const meta: Meta = {
    title: 'Products/Workflows/Editor/Tile canvas',
    parameters: {
        layout: 'fullscreen',
        featureFlags: [FEATURE_FLAGS.WORKFLOWS_TILE_CANVAS],
        mockDate: '2026-10-10 12:00:00',
        testOptions: {
            waitForLoadersToDisappear: true,
            waitForSelector: '.react-flow__node',
            viewport: { width: 1440, height: 900 },
        },
    },
    decorators: [createWorkflowEditorStoryDecorator(TILE_CANVAS_WORKFLOWS)],
}
export default meta

function StoryState({
    metrics,
    openAllPaths,
}: {
    metrics?: Record<string, HogFlowEditorActionMetrics>
    openAllPaths?: boolean
}): null {
    const { logicProps } = useValues(workflowLogic)
    const { loadStepCountsSuccess, toggleAllPaths } = useActions(tileCanvasLogic(logicProps))
    useEffect(() => {
        if (metrics) {
            loadStepCountsSuccess(metrics)
        }
        if (openAllPaths) {
            toggleAllPaths()
        }
    }, [metrics, openAllPaths, loadStepCountsSuccess, toggleAllPaths])
    return null
}

function StoryEditor({
    metrics,
    openAllPaths,
}: {
    metrics?: Record<string, HogFlowEditorActionMetrics>
    openAllPaths?: boolean
}): JSX.Element {
    const { originalWorkflow } = useValues(workflowLogic)
    const tileCanvasEnabled = useFeatureFlag('WORKFLOWS_TILE_CANVAS')
    return (
        <div className="flex h-full flex-col">
            {originalWorkflow ? (
                <>
                    <HogFlowEditor key={originalWorkflow.id} isTreeView={false} isTileCanvas={!!tileCanvasEnabled} />
                    <StoryState metrics={metrics} openAllPaths={openAllPaths} />
                </>
            ) : (
                <SpinnerOverlay />
            )}
        </div>
    )
}

function canvasStory(
    id: string,
    state: { metrics?: Record<string, HogFlowEditorActionMetrics>; openAllPaths?: boolean } = {}
): StoryFn {
    const Story: StoryFn = () => (
        <BindLogic logic={workflowLogic} props={{ id }}>
            <div className="h-screen">
                <StoryEditor {...state} />
            </div>
        </BindLogic>
    )
    return Story
}

export const PathsCollapsed = canvasStory(AI_SUPPORT_TRIAGE.id)
export const PathsOpen = canvasStory(AI_SUPPORT_TRIAGE.id, { openAllPaths: true })
export const WithStepCounts = canvasStory(TRIAL_TO_PAID.id, { metrics: TRIAL_TO_PAID_METRICS })
export const TimeWindowAndWebhook = canvasStory(TICKET_TO_SLACK.id, { openAllPaths: true })
export const LongEmails = canvasStory(LONG_EMAILS.id)
