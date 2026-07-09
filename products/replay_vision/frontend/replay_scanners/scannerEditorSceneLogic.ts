import { actions, afterMount, kea, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import { router, urlToAction } from 'kea-router'

import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'

import { Breadcrumb } from '~/types'

import { visionScannersSelfDrivingAvailabilityRetrieve } from '../generated/api'
import type { scannerEditorSceneLogicType } from './scannerEditorSceneLogicType'

export type ScannerEditorStep = 'template' | 'configure' | 'triggers' | 'self_driving'
export const SCANNER_EDITOR_STEPS: readonly ScannerEditorStep[] = ['template', 'configure', 'triggers', 'self_driving']
export const SCANNER_EDITOR_STEP_ORDER: Record<ScannerEditorStep, number> = {
    template: 0,
    configure: 1,
    triggers: 2,
    self_driving: 3,
}

export function scannerStepUrl(step: ScannerEditorStep, scannerId: string): string {
    switch (step) {
        case 'template':
            return urls.replayVisionScannerTemplate(scannerId)
        case 'configure':
            return urls.replayVisionScannerConfigure(scannerId)
        case 'triggers':
            return urls.replayVisionScannerTriggers(scannerId)
        case 'self_driving':
            return urls.replayVisionScannerSelfDriving(scannerId)
    }
}

export const scannerEditorSceneLogic = kea<scannerEditorSceneLogicType>([
    path(['products', 'replay_vision', 'frontend', 'replay_scanners', 'scannerEditorSceneLogic']),

    actions({
        setScannerId: (scannerId: string) => ({ scannerId }),
        setStep: (step: ScannerEditorStep) => ({ step }),
    }),

    reducers({
        scannerId: [
            'new' as string,
            {
                setScannerId: (_, { scannerId }) => scannerId,
            },
        ],
        step: [
            'configure' as ScannerEditorStep,
            {
                setStep: (_, { step }) => step,
            },
        ],
    }),

    loaders({
        // Whether the team has a Signals/responder setup that would consume scanner findings, gating the
        // self-driving step. Defaults false so the step stays hidden until the check confirms availability.
        selfDrivingAvailable: [
            false,
            {
                loadSelfDrivingAvailable: async () => {
                    const teamId = teamLogic.values.currentTeamId
                    if (!teamId) {
                        return false
                    }
                    const response = await visionScannersSelfDrivingAvailabilityRetrieve(String(teamId))
                    return response.available
                },
            },
        ],
    }),

    selectors({
        isNew: [(s) => [s.scannerId], (scannerId: string): boolean => scannerId === 'new'],
        visibleSteps: [
            (s) => [s.isNew, s.selfDrivingAvailable],
            (isNew: boolean, selfDrivingAvailable: boolean): readonly ScannerEditorStep[] =>
                SCANNER_EDITOR_STEPS.filter(
                    (step) => (isNew || step !== 'template') && (selfDrivingAvailable || step !== 'self_driving')
                ),
        ],
        breadcrumbs: [
            (s) => [s.scannerId, s.isNew],
            (scannerId: string, isNew: boolean): Breadcrumb[] => {
                const crumbs: Breadcrumb[] = [
                    {
                        key: 'replay-vision',
                        name: 'Replay vision',
                        path: urls.replayVision(),
                        iconType: 'replay_vision',
                    },
                ]
                if (isNew) {
                    crumbs.push({ key: 'new-scanner', name: 'New scanner', path: urls.replayVision('new') })
                    return crumbs
                }
                // Editing an existing scanner: surface the detail page (on its Configuration tab, where the
                // Edit button lives) as an intermediate crumb so the back arrow returns there, not to the list.
                crumbs.push(
                    {
                        key: `scanner-${scannerId}`,
                        name: 'Scanner',
                        path: `${urls.replayVision(scannerId)}?tab=configuration`,
                    },
                    {
                        key: `scanner-${scannerId}-edit`,
                        name: 'Edit',
                        path: urls.replayVisionScannerConfigure(scannerId),
                    }
                )
                return crumbs
            },
        ],
    }),

    urlToAction(({ actions, values }) => ({
        [urls.replayVisionScannerTemplate(':id')]: ({ id }) => {
            const scannerId = id || 'new'
            if (scannerId !== 'new') {
                router.actions.replace(urls.replayVisionScannerConfigure(scannerId))
                return
            }
            if (scannerId !== values.scannerId) {
                actions.setScannerId(scannerId)
            }
            if (values.step !== 'template') {
                actions.setStep('template')
            }
        },
        [urls.replayVisionScannerConfigure(':id')]: ({ id }) => {
            const scannerId = id || 'new'
            if (scannerId !== values.scannerId) {
                actions.setScannerId(scannerId)
            }
            if (values.step !== 'configure') {
                actions.setStep('configure')
            }
        },
        [urls.replayVisionScannerTriggers(':id')]: ({ id }) => {
            const scannerId = id || 'new'
            if (scannerId !== values.scannerId) {
                actions.setScannerId(scannerId)
            }
            if (values.step !== 'triggers') {
                actions.setStep('triggers')
            }
        },
        [urls.replayVisionScannerSelfDriving(':id')]: ({ id }) => {
            const scannerId = id || 'new'
            if (scannerId !== values.scannerId) {
                actions.setScannerId(scannerId)
            }
            if (values.step !== 'self_driving') {
                actions.setStep('self_driving')
            }
        },
    })),

    afterMount(({ actions }) => {
        actions.loadSelfDrivingAvailable()
    }),
])
