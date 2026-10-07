import { NewWorkflowButton } from '../Workflows/NewWorkflowButton'
import { NewWorkflowModal } from '../Workflows/NewWorkflowModal'

export function NewWorkflowEmptyStateAction({ onClick }: { onClick: () => void }): JSX.Element {
    return (
        <>
            <NewWorkflowButton className="self-start" onClick={onClick} />
            <NewWorkflowModal />
        </>
    )
}
