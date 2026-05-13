import { actions, kea, listeners, path, reducers, selectors } from 'kea'

import type { founderModeLogicType } from './founderModeLogicType'

export interface FounderModeSubStep {
    key: string
    title: string
}

export interface FounderModeStep {
    key: string
    title: string
    subSteps: FounderModeSubStep[]
}

export const FOUNDER_MODE_STEPS: FounderModeStep[] = [
    {
        key: 'idea',
        title: 'Idea',
        subSteps: [
            { key: 'problem', title: 'Frame the problem' },
            { key: 'solution', title: 'Sketch a solution' },
            { key: 'differentiation', title: 'Why you' },
        ],
    },
    {
        key: 'audience',
        title: 'Audience',
        subSteps: [
            { key: 'icp', title: 'Ideal customer' },
            { key: 'channels', title: 'Where they hang out' },
        ],
    },
    {
        key: 'mvp',
        title: 'MVP',
        subSteps: [
            { key: 'scope', title: 'Scope cuts' },
            { key: 'build', title: 'Build the slice' },
            { key: 'instrument', title: 'Instrument with PostHog' },
        ],
    },
    {
        key: 'launch',
        title: 'Launch',
        subSteps: [
            { key: 'beta', title: 'Closed beta' },
            { key: 'public', title: 'Public launch' },
        ],
    },
    {
        key: 'learn',
        title: 'Learn',
        subSteps: [
            { key: 'metrics', title: 'Look at the numbers' },
            { key: 'iterate', title: 'Iterate' },
        ],
    },
]

export interface FounderModePosition {
    stepIndex: number
    subStepIndex: number
}

function clampPosition({ stepIndex, subStepIndex }: FounderModePosition): FounderModePosition {
    const safeStepIndex = Math.max(0, Math.min(FOUNDER_MODE_STEPS.length - 1, stepIndex))
    const subCount = FOUNDER_MODE_STEPS[safeStepIndex].subSteps.length
    const safeSubStepIndex = Math.max(0, Math.min(subCount - 1, subStepIndex))
    return { stepIndex: safeStepIndex, subStepIndex: safeSubStepIndex }
}

export const founderModeLogic = kea<founderModeLogicType>([
    path(['products', 'founder_mode', 'founderModeLogic']),
    actions({
        nextStep: true,
        previousStep: true,
        setStep: (stepIndex: number, subStepIndex: number = 0) => ({ stepIndex, subStepIndex }),
    }),
    reducers({
        position: [
            { stepIndex: 0, subStepIndex: 0 } as FounderModePosition,
            {
                setStep: (_, { stepIndex, subStepIndex }) => clampPosition({ stepIndex, subStepIndex }),
            },
        ],
    }),
    listeners(({ actions, values }) => ({
        nextStep: () => {
            const { stepIndex, subStepIndex } = values.position
            const step = FOUNDER_MODE_STEPS[stepIndex]
            if (subStepIndex < step.subSteps.length - 1) {
                actions.setStep(stepIndex, subStepIndex + 1)
            } else if (stepIndex < FOUNDER_MODE_STEPS.length - 1) {
                actions.setStep(stepIndex + 1, 0)
            }
        },
        previousStep: () => {
            const { stepIndex, subStepIndex } = values.position
            if (subStepIndex > 0) {
                actions.setStep(stepIndex, subStepIndex - 1)
            } else if (stepIndex > 0) {
                const prevStep = FOUNDER_MODE_STEPS[stepIndex - 1]
                actions.setStep(stepIndex - 1, prevStep.subSteps.length - 1)
            }
        },
    })),
    selectors({
        steps: [() => [], (): FounderModeStep[] => FOUNDER_MODE_STEPS],
        currentStep: [(s) => [s.position], (position): FounderModeStep => FOUNDER_MODE_STEPS[position.stepIndex]],
        currentSubStep: [
            (s) => [s.position],
            (position): FounderModeSubStep => FOUNDER_MODE_STEPS[position.stepIndex].subSteps[position.subStepIndex],
        ],
        isFirstStep: [
            (s) => [s.position],
            (position): boolean => position.stepIndex === 0 && position.subStepIndex === 0,
        ],
        isLastStep: [
            (s) => [s.position],
            (position): boolean => {
                const lastStepIndex = FOUNDER_MODE_STEPS.length - 1
                const lastSubStepIndex = FOUNDER_MODE_STEPS[lastStepIndex].subSteps.length - 1
                return position.stepIndex === lastStepIndex && position.subStepIndex === lastSubStepIndex
            },
        ],
    }),
])
