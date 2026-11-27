import { act, cleanup, render } from '@testing-library/react'
import posthog from 'posthog-js'
import { createElement } from 'react'

import { ScenePanelColumn } from '~/layout/navigation-3000/components/ScenePanelColumn'
import { SidePanelInfo } from '~/layout/navigation-3000/sidepanel/panels/info/SidePanelInfo'
import { ScenePanel } from '~/layout/scenes/SceneLayout'
import { sceneLayoutLogic } from '~/layout/scenes/sceneLayoutLogic'
import { initKeaTests } from '~/test/init'
import { PropertyFilterType, PropertyOperator } from '~/types'

import {
    MessageAudience,
    MessageAudienceDestination,
    captureMessageAudienceClicked,
    captureMessageAudienceShown,
    messageAudienceUrl,
} from './messageAudience'
import { rememberSavedWorkflowAttempt, workflowEntryAttempt } from './messageAudienceAttempts'
import { MessageAudienceShownInScenePanel } from './MessageAudienceShownInScenePanel'

function audienceFrom(source: string): MessageAudience {
    return {
        source,
        properties: [{ key: 'id', type: PropertyFilterType.Cohort, value: 7, operator: PropertyOperator.In }],
    }
}

function attemptInUrl(source: string, destination: MessageAudienceDestination): string | null {
    return new URL(messageAudienceUrl(audienceFrom(source), destination), 'https://app.example.com').searchParams.get(
        'attempt'
    )
}

describe('message audience attempts', () => {
    let capture: jest.SpyInstance

    beforeEach(() => {
        capture = jest.spyOn(posthog, 'capture').mockImplementation(() => undefined)
    })

    afterEach(() => {
        cleanup()
        capture.mockRestore()
    })

    function captured(event: string): Record<string, unknown>[] {
        return capture.mock.calls.filter(([name]) => name === event).map(([, properties]) => properties)
    }

    it('reports a spot shown once, and carries its attempt through the click into the editor URL', () => {
        captureMessageAudienceShown('early_access', 'workflow')
        captureMessageAudienceShown('early_access', 'workflow')
        captureMessageAudienceClicked('early_access', 'workflow')

        const [shown, ...repeated] = captured('message audience shown')
        expect(repeated).toEqual([])
        expect(shown).toEqual({ source: 'early_access', destination: 'workflow', attempt_id: expect.any(String) })
        expect(captured('message audience clicked')).toEqual([
            { source: 'early_access', destination: 'workflow', attempt_id: shown.attempt_id },
        ])
        expect(attemptInUrl('early_access', 'workflow')).toEqual(shown.attempt_id)
    })

    it('gives each destination of one source its own attempt', () => {
        captureMessageAudienceShown('cohort', 'broadcast')
        captureMessageAudienceShown('cohort', 'workflow')

        const [broadcast, workflow] = captured('message audience shown')
        expect(broadcast.attempt_id).not.toEqual(workflow.attempt_id)
        expect(attemptInUrl('cohort', 'broadcast')).toEqual(broadcast.attempt_id)
        expect(attemptInUrl('cohort', 'workflow')).toEqual(workflow.attempt_id)
    })

    it('starts the attempt at the click when the spot never reported it was shown', () => {
        captureMessageAudienceClicked('survey_respondents', 'broadcast')

        const [clicked] = captured('message audience clicked')
        expect(clicked.attempt_id).toEqual(expect.any(String))
        expect(attemptInUrl('survey_respondents', 'broadcast')).toEqual(clicked.attempt_id)
    })

    it('keeps the attempt of a saved workflow when the page reloads', () => {
        rememberSavedWorkflowAttempt('workflow-1', '0195f3a2-7c4e-7d10-9a6b-2f3c4d5e6f71')

        jest.isolateModules(() => {
            const { workflowEntryAttempt } = jest.requireActual('./messageAudienceAttempts')
            expect(workflowEntryAttempt({ id: 'workflow-1' })).toEqual('0195f3a2-7c4e-7d10-9a6b-2f3c4d5e6f71')
            expect(workflowEntryAttempt({ id: 'workflow-2' })).toBeUndefined()
        })
    })

    it('keeps the attempt of a saved workflow in the tab when session storage refuses the write', () => {
        const setItem = jest.spyOn(Storage.prototype, 'setItem').mockImplementation(() => {
            throw new Error('QuotaExceededError')
        })
        try {
            rememberSavedWorkflowAttempt('workflow-3', '0195f3a2-7c4e-7d10-9a6b-2f3c4d5e6f72')
        } finally {
            setItem.mockRestore()
        }

        expect(workflowEntryAttempt({ id: 'workflow-3' })).toEqual('0195f3a2-7c4e-7d10-9a6b-2f3c4d5e6f72')
    })

    function renderInScenePanel(host: () => JSX.Element | null, source: string): void {
        initKeaTests()
        sceneLayoutLogic.mount()
        render(
            createElement(
                'div',
                null,
                createElement(
                    ScenePanel,
                    null,
                    createElement(MessageAudienceShownInScenePanel, { source, destination: 'broadcast' })
                ),
                createElement(host)
            )
        )
    }

    it('reports a scene panel spot shown only once the inline panel opens', () => {
        renderInScenePanel(ScenePanelColumn, 'inline_panel')
        expect(captured('message audience shown')).toEqual([])

        act(() => sceneLayoutLogic.actions.setScenePanelOpen(true))

        expect(captured('message audience shown')).toEqual([
            { source: 'inline_panel', destination: 'broadcast', attempt_id: expect.any(String) },
        ])
    })

    it('reports a scene panel spot shown when the Actions pane shows it outside the side panel', () => {
        renderInScenePanel(SidePanelInfo, 'actions_pane')

        expect(sceneLayoutLogic.values.scenePanelOpen).toBe(false)
        expect(captured('message audience shown')).toEqual([
            { source: 'actions_pane', destination: 'broadcast', attempt_id: expect.any(String) },
        ])
    })

    it('opens the editor without an attempt from a spot that was never shown or clicked', () => {
        expect(attemptInUrl('autoresearch', 'workflow')).toBeNull()
    })
})
