import { BindLogic } from 'kea'

import { WorkflowLogicProps } from '../../../workflowLogic'
import { CanvasCommandButtons } from './CanvasCommandButtons'
import { tileCanvasLogic } from './tileCanvasLogic'

/** The workflow bar sits outside the canvas's logic binding, so it binds the canvas logic itself. */
export function CanvasCommandGroup(props: WorkflowLogicProps): JSX.Element {
    return (
        <BindLogic logic={tileCanvasLogic} props={props}>
            <CanvasCommandButtons />
        </BindLogic>
    )
}
