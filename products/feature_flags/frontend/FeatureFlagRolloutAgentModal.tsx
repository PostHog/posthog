import { useActions, useValues } from 'kea'
import { Form } from 'kea-forms'

import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { LemonInput } from 'lib/lemon-ui/LemonInput'
import { LemonModal } from 'lib/lemon-ui/LemonModal'
import { LemonSelect } from 'lib/lemon-ui/LemonSelect'
import { LemonTextArea } from 'lib/lemon-ui/LemonTextArea'
import { featureFlagLogic } from 'scenes/feature-flags/featureFlagLogic'

import { featureFlagRolloutAgentLogic } from './featureFlagRolloutAgentLogic'

export function FeatureFlagRolloutAgentModal({ flagId }: { flagId: number }): JSX.Element {
    const logic = featureFlagRolloutAgentLogic({ id: flagId })
    const { isSetupModalOpen, isSetupSubmitting } = useValues(logic)
    const { closeSetupModal, submitSetup } = useActions(logic)
    const { featureFlag } = useValues(featureFlagLogic)
    const groups = featureFlag.filters?.groups ?? []

    return (
        <LemonModal
            isOpen={isSetupModalOpen}
            onClose={closeSetupModal}
            title="Set up an agent rollout"
            description="A PostHog AI agent checks the results before each step. If they pass, PostHog raises the flag to your next percentage. If a check fails, the rollout stops at its current percentage and you get a notification."
            footer={
                <>
                    <LemonButton type="secondary" onClick={closeSetupModal}>
                        Cancel
                    </LemonButton>
                    <LemonButton
                        type="primary"
                        data-attr="feature-flag-rollout-agent-start"
                        loading={isSetupSubmitting}
                        onClick={submitSetup}
                    >
                        Approve and start
                    </LemonButton>
                </>
            }
        >
            <Form logic={featureFlagRolloutAgentLogic} props={{ id: flagId }} formKey="setup" className="space-y-3">
                {groups.length > 1 && (
                    <LemonField name="conditionIndex" label="Release condition">
                        <LemonSelect
                            options={groups.map((group, index) => ({
                                value: index,
                                label: `Condition ${index + 1} (${group.rollout_percentage ?? 100}%)`,
                            }))}
                        />
                    </LemonField>
                )}
                <LemonField
                    name="percentages"
                    label="Percentages"
                    help="In increasing order, separated by commas. The first one must be higher than the current rollout."
                >
                    <LemonInput placeholder="5, 25, 50, 100" />
                </LemonField>
                <LemonField name="soakHours" label="Hours between steps">
                    <LemonInput type="number" min={1} />
                </LemonField>
                <LemonField
                    name="healthChecks"
                    label="Health checks"
                    help="Name the insights or dashboards that show the feature is healthy, and the result that should stop the rollout."
                >
                    <LemonTextArea placeholder="Stop if the error rate on the checkout dashboard passes 2%." />
                </LemonField>
                <p className="text-secondary text-sm mb-0">
                    By approving, you let the agent raise this flag up to your highest percentage without asking you
                    again. You can stop the rollout at any time from this page.
                </p>
            </Form>
        </LemonModal>
    )
}
