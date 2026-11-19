import { SceneSection } from '~/layout/scenes/components/SceneSection'

import { AutoApprovalRuns } from './AutoApprovalRuns'

export function ApprovalHistory(): JSX.Element {
    return (
        <SceneSection
            title="Approval history"
            description="Each time auto-approval reviewed a pull request, and what it decided."
        >
            <AutoApprovalRuns />
        </SceneSection>
    )
}
