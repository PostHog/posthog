import { BindLogic, useActions, useValues } from 'kea'

import { LemonButton, LemonModal, LemonSkeleton, Link } from '@posthog/lemon-ui'

import { KeyboardShortcut } from 'lib/lemon-ui/KeyboardShortcut/KeyboardShortcut'

import { goalScoutFormLogic, type GoalFormStep } from '../../../../logics/goal/goalScoutFormLogic'
import { MIN_BELIEF_FOR_MEASURES } from '../../../../utils/goal/form'
import { GoalBeliefField } from './GoalBeliefField'
import { GoalFormStatus } from './GoalFormStatus'
import { GoalOwnerIdeasField } from './GoalOwnerIdeasField'
import { GoalPlanFields } from './GoalPlanFields'

const FORM_ID = 'goal-scout-form'

const TITLES: Record<GoalFormStep, [string, string | undefined]> = {
    belief: ['What do you believe?', 'Write what you think is true about your users, and why.'],
    plan: ['Check the plan', 'Filled in from your belief. Change anything that looks wrong.'],
    ideas: [
        'Any ideas of your own?',
        'Optional. The scout checks them against your data, next to its own ideas. Nothing is built until you choose.',
    ],
}

export interface GoalScoutFormModalProps {
    isOpen: boolean
    onClose: () => void
    goalId: string
}

export function GoalScoutFormModal({ isOpen, onClose, goalId }: GoalScoutFormModalProps): JSX.Element {
    const logicProps = { id: goalId, onClose }
    const logic = goalScoutFormLogic(logicProps)
    const {
        goalForm,
        isGoalFormSubmitting,
        goalFormChanged,
        isNew,
        existing,
        existingLoading,
        submitError,
        step,
        submitDisabledReason,
    } = useValues(logic)
    const { goToPlan, goToIdeas, setStep, submitGoalForm } = useActions(logic)
    const handleClose = (): void => {
        if (!isGoalFormSubmitting) {
            onClose()
        }
    }
    const beliefShort = goalForm.statement.trim().length < MIN_BELIEF_FOR_MEASURES
    const loaded = isNew || (!existingLoading && !!existing)
    const busyReason = isGoalFormSubmitting ? (isNew ? 'Creating the scout' : 'Saving the scout') : undefined
    const [title, description] = isNew ? TITLES[step] : ['Edit goal scout', undefined]
    const back = (target: GoalFormStep): JSX.Element => (
        <LemonButton
            type="secondary"
            disabledReason={busyReason}
            onClick={() => setStep(target)}
            data-attr="goal-scout-form-back"
        >
            Back
        </LemonButton>
    )
    const submit = (
        <LemonButton
            type="primary"
            loading={isGoalFormSubmitting}
            disabledReason={loaded ? (submitDisabledReason ?? undefined) : 'Loading the scout'}
            form={FORM_ID}
            htmlType="submit"
            data-attr={isNew ? 'goal-scout-form-create' : 'goal-scout-form-save'}
        >
            {isNew ? 'Create scout' : 'Save changes'}
        </LemonButton>
    )
    const footer =
        step === 'belief' ? (
            <>
                <div className="flex-1" />
                <LemonButton type="secondary" onClick={handleClose}>
                    Cancel
                </LemonButton>
                <LemonButton
                    type="primary"
                    onClick={goToPlan}
                    disabledReason={beliefShort ? 'Write your belief in a full sentence' : undefined}
                    sideIcon={<KeyboardShortcut command enter />}
                    data-attr="goal-scout-form-continue"
                >
                    Continue
                </LemonButton>
            </>
        ) : step === 'ideas' ? (
            <>
                <GoalFormStatus />
                {back('plan')}
                {submit}
            </>
        ) : (
            <>
                <GoalFormStatus />
                {isNew ? (
                    back('belief')
                ) : (
                    <LemonButton type="secondary" disabledReason={busyReason} onClick={handleClose}>
                        Cancel
                    </LemonButton>
                )}
                {isNew ? (
                    <LemonButton
                        type="primary"
                        form={FORM_ID}
                        htmlType="submit"
                        disabledReason={submitDisabledReason ?? undefined}
                        data-attr="goal-scout-form-to-ideas"
                    >
                        Continue
                    </LemonButton>
                ) : (
                    submit
                )}
            </>
        )

    return (
        <BindLogic logic={goalScoutFormLogic} props={logicProps}>
            <LemonModal
                isOpen={isOpen}
                onClose={handleClose}
                title={title}
                description={description}
                width={720}
                hasUnsavedInput={goalFormChanged}
                footer={<div className="flex w-full flex-wrap items-center justify-end gap-2">{footer}</div>}
            >
                {existingLoading ? (
                    <div className="flex flex-col gap-4">
                        <LemonSkeleton className="h-20 w-full" />
                        <LemonSkeleton className="h-10 w-full" />
                        <LemonSkeleton className="h-10 w-full" />
                    </div>
                ) : !loaded ? (
                    <p className="m-0 text-danger">
                        {submitError?.message || "Couldn't load this scout. Close this and try again."}
                    </p>
                ) : step === 'belief' ? (
                    <GoalBeliefField large onSubmit={goToPlan} />
                ) : (
                    <form
                        id={FORM_ID}
                        noValidate
                        onSubmit={(event) => {
                            event.preventDefault()
                            if (isNew && step === 'plan') {
                                goToIdeas()
                            } else if (!submitDisabledReason && !isGoalFormSubmitting) {
                                submitGoalForm()
                            }
                        }}
                    >
                        {step === 'ideas' ? (
                            <GoalOwnerIdeasField />
                        ) : (
                            <div className="@container flex flex-col gap-4">
                                {isNew ? (
                                    <p className="m-0 text-sm text-secondary">
                                        <span className="font-semibold text-primary">Your belief:</span>{' '}
                                        {goalForm.statement.trim()}{' '}
                                        <Link onClick={() => setStep('belief')} data-attr="goal-scout-form-edit-belief">
                                            Edit
                                        </Link>
                                    </p>
                                ) : (
                                    <GoalBeliefField />
                                )}
                                <GoalPlanFields />
                            </div>
                        )}
                    </form>
                )}
            </LemonModal>
        </BindLogic>
    )
}
