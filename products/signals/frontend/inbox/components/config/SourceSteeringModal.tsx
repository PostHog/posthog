import { useActions, useValues } from 'kea'
import { Form } from 'kea-forms'
import { useId } from 'react'

import { LemonBanner, LemonButton, LemonCollapse, LemonModal, LemonSelect, LemonTextArea } from '@posthog/lemon-ui'

import { LemonField } from 'lib/lemon-ui/LemonField'

import {
    SourceSteeringModalLogicProps,
    sourceHasLegacyPosture,
    sourceSteeringModalLogic,
} from '../../logics/sourceSteeringModalLogic'
import { SOURCE_STEERING_MAX_LENGTH, SignalSourceConfig } from '../../types'

export interface SourceSteeringModalProps {
    /** Every config row this source's guidance is saved to. See `SourceSteeringModalLogicProps`. */
    sourceConfigs: SignalSourceConfig[]
    /** The roster label of the source being steered, for the modal title. */
    sourceLabel: string
    onClose: () => void
}

export function SourceSteeringModal({ sourceConfigs, sourceLabel, onClose }: SourceSteeringModalProps): JSX.Element {
    const formId = useId()
    const logicProps: SourceSteeringModalLogicProps = { sourceConfigs, onClose }
    const logic = sourceSteeringModalLogic(logicProps)
    const {
        isSourceSteeringSubmitting,
        sourceSteeringChanged,
        sourceSteeringValidationErrors,
        steeringExamples,
        sourceSteering,
        researchSkills,
        researchSkillsLoading,
        researchSkillsFailed,
    } = useValues(logic)
    const { setSourceSteeringValue, loadResearchSkills } = useActions(logic)

    const handleClose = (): void => {
        if (isSourceSteeringSubmitting) {
            return
        }
        onClose()
    }

    const steeringError =
        typeof sourceSteeringValidationErrors.steering === 'string'
            ? sourceSteeringValidationErrors.steering
            : undefined

    return (
        <LemonModal
            isOpen
            onClose={handleClose}
            title={`Guidance for ${sourceLabel}`}
            description={`Tell the agent what matters and what to skip in ${sourceLabel}. It reads this when deciding what turns into a report. Leave it empty and it uses its own judgment.`}
            width={560}
            hasUnsavedInput={sourceSteeringChanged}
            footer={
                <>
                    <LemonButton
                        type="secondary"
                        onClick={handleClose}
                        disabledReason={isSourceSteeringSubmitting ? 'Saving' : undefined}
                    >
                        Cancel
                    </LemonButton>
                    <LemonButton
                        type="primary"
                        form={formId}
                        htmlType="submit"
                        loading={isSourceSteeringSubmitting}
                        disabledReason={steeringError}
                        data-attr="signal-source-steering-save"
                    >
                        Save
                    </LemonButton>
                </>
            }
        >
            <Form
                logic={sourceSteeringModalLogic}
                props={logicProps}
                formKey="sourceSteering"
                id={formId}
                enableFormOnSubmit
            >
                <div className="flex flex-col gap-3">
                    {sourceConfigs.some(sourceHasLegacyPosture) && (
                        <LemonBanner type="info">
                            This source only reports records that clearly qualify. Saving here replaces that with what
                            you write below.
                        </LemonBanner>
                    )}
                    <LemonField
                        name="steering"
                        help="Applies from the next sync. Nothing already in your inbox changes."
                    >
                        <LemonTextArea
                            minRows={4}
                            maxRows={10}
                            maxLength={SOURCE_STEERING_MAX_LENGTH}
                            // The field has no visible label by design, so name it for screen readers.
                            aria-label={`Guidance for ${sourceLabel}`}
                            placeholder="Write it like a note to a teammate."
                            disabled={isSourceSteeringSubmitting}
                            data-attr="signal-source-steering-rules"
                        />
                    </LemonField>
                    <LemonCollapse
                        onChange={() => {
                            if (researchSkills === null && !researchSkillsLoading) {
                                loadResearchSkills()
                            }
                        }}
                        panels={[
                            {
                                key: 'research-skill',
                                header: sourceSteering.researchSkill
                                    ? `Research skill: ${sourceSteering.researchSkill}`
                                    : sourceSteering.researchSkill === null
                                      ? 'Research skills: multiple selections'
                                      : 'Research skill: default',
                                content: (
                                    <div className="flex flex-col gap-2">
                                        <p className="m-0 text-secondary">
                                            Add a project skill to the default research agent. It can use the existing
                                            MCP tools and shared scratchpad. Permissions stay the same.
                                        </p>
                                        {researchSkillsFailed ? (
                                            <LemonBanner type="error">
                                                Could not load skills.{' '}
                                                <LemonButton type="tertiary" size="small" onClick={loadResearchSkills}>
                                                    Try again
                                                </LemonButton>
                                            </LemonBanner>
                                        ) : (
                                            <LemonSelect
                                                fullWidth
                                                value={sourceSteering.researchSkill ?? ''}
                                                onChange={(value) => setSourceSteeringValue('researchSkill', value)}
                                                loading={researchSkillsLoading}
                                                disabledReason={isSourceSteeringSubmitting ? 'Saving' : undefined}
                                                options={[
                                                    { value: '', label: 'Default research (no custom skill)' },
                                                    ...(sourceSteering.researchSkill &&
                                                    !researchSkills?.some(
                                                        (skill) => skill.name === sourceSteering.researchSkill
                                                    )
                                                        ? [
                                                              {
                                                                  value: sourceSteering.researchSkill,
                                                                  label: sourceSteering.researchSkill,
                                                              },
                                                          ]
                                                        : []),
                                                    ...(researchSkills ?? []).map((skill) => ({
                                                        value: skill.name,
                                                        label: skill.name,
                                                        tooltip: skill.description,
                                                    })),
                                                ]}
                                                data-attr="signal-source-research-skill"
                                            />
                                        )}
                                        {sourceSteering.researchSkill === null && (
                                            <p className="m-0 text-secondary">
                                                These source types use different skills. Select a skill to change all of
                                                them.
                                            </p>
                                        )}
                                        <p className="m-0 text-secondary">
                                            Applies to the next research run. Runs already started keep their selected
                                            version.
                                        </p>
                                    </div>
                                ),
                            },
                        ]}
                    />
                    <div className="flex flex-col gap-1">
                        <span className="text-xs text-secondary">Need a starting point? Click one to add it.</span>
                        <div className="flex flex-wrap gap-1">
                            {steeringExamples.map((example) => (
                                <LemonButton
                                    key={example.label}
                                    type="secondary"
                                    size="xsmall"
                                    tooltip={example.line}
                                    // A string tooltip would otherwise become the whole accessible
                                    // name, hiding the visible label from speech control.
                                    aria-label={`${example.label}: adds "${example.line}"`}
                                    onClick={() => setSourceSteeringValue('steering', example.result)}
                                    disabledReason={
                                        isSourceSteeringSubmitting
                                            ? 'Saving'
                                            : !example.fits
                                              ? "This example won't fit in what you've written"
                                              : undefined
                                    }
                                >
                                    {example.label}
                                </LemonButton>
                            ))}
                        </div>
                    </div>
                </div>
            </Form>
        </LemonModal>
    )
}
