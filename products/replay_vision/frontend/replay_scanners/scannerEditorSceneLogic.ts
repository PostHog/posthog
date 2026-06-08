import { actions, kea, path, reducers, selectors } from 'kea'
import { urlToAction } from 'kea-router'

import { urls } from 'scenes/urls'

import { Breadcrumb } from '~/types'

import type { scannerEditorSceneLogicType } from './scannerEditorSceneLogicType'

export type ScannerEditorStep = 'configure' | 'triggers'
export const SCANNER_EDITOR_STEPS: readonly ScannerEditorStep[] = ['configure', 'triggers']

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
