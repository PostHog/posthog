import { actions, kea, path, reducers, selectors } from 'kea'
import { router, urlToAction } from 'kea-router'

import { urls } from 'scenes/urls'

import { Breadcrumb } from '~/types'

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

    selectors({
        isNew: [(s) => [s.scannerId], (scannerId: string): boolean => scannerId === 'new'],
        visibleSteps: [
            (s) => [s.isNew],
            (isNew: boolean): readonly ScannerEditorStep[] =>
                // The template picker only exists for a new scanner; every other step, self-driving included, always shows.
                SCANNER_EDITOR_STEPS.filter((step) => isNew || step !== 'template'),
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
])
