import { useActions, useValues } from 'kea'

import { LemonButton } from '@posthog/lemon-ui'

import { SceneExport } from 'scenes/sceneTypes'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'

import { Step1 } from '../components/Step1'
import { Step2 } from '../components/Step2'
import { Step3 } from '../components/Step3'
import { Step4 } from '../components/Step4'
import { founderLogic } from './founderLogic'
export const scene: SceneExport = {
    component: FoundersScene,
    logic: founderLogic,
}

export function FoundersScene(): JSX.Element {
    const { step } = useValues(founderLogic)
    const { setStep } = useActions(founderLogic)
    return (
        <>
            <SceneTitleSection name="Founder mode" resourceType={{ type: 'founder_mode' }} />
            <SceneContent>
                <div className="space-y-4">
                    <p>Welcome to Founder mode.</p>
                    {step === 1 && <Step1 />}
                    {step === 2 && <Step2 />}
                    {step === 3 && <Step3 />}
                    {step === 4 && <Step4 />}
                    <LemonButton onClick={() => setStep(step + 1)}>Next</LemonButton>
                    <LemonButton onClick={() => setStep(step - 1)} disabled={step === 0}>
                        Previous
                    </LemonButton>
                </div>
            </SceneContent>
        </>
    )
}
