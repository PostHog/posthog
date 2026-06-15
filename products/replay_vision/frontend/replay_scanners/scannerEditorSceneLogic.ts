import { actions, kea, path, reducers, selectors } from 'kea'
import { router, urlToAction } from 'kea-router'

import { urls } from 'scenes/urls'

import { Breadcrumb } from '~/types'

import type { scannerEditorSceneLogicType } from './scannerEditorSceneLogicType'

export type ScannerEditorStep = 'template' | 'configure' | 'triggers'
export const SCANNER_EDITOR_STEPS: readonly ScannerEditorStep[] = ['template', 'configure', 'triggers']
export const SCANNER_EDITOR_STEP_ORDER: Record<ScannerEditorStep, number> = {
    template: 0,
    configure: 1,
    triggers: 2,
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
                isNew ? SCANNER_EDITOR_STEPS : SCANNER_EDITOR_STEPS.filter((s) => s !== 'template'),
        ],
        breadcrumbs: [
            (s) => [s.scannerId, s.isNew],
            (scannerId: string, isNew: boolean): Breadcrumb[] => [
                {
                    key: 'replay-vision',
                    name: 'Replay vision',
                    path: urls.replayVision(),
                    iconType: 'replay_vision',
                },
                {
                    key: isNew ? 'new-scanner' : `scanner-${scannerId}`,
                    name: isNew ? 'New scanner' : 'Scanner',
                    path: urls.replayVision(scannerId),
                },
            ],
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
    })),
])
