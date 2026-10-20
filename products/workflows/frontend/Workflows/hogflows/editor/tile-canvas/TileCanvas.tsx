import './TileCanvas.scss'

import { BindLogic, useValues } from 'kea'

import { workflowLogic } from '../../../workflowLogic'
import { TileCanvasContent } from './TileCanvasContent'
import { tileCanvasLogic } from './tileCanvasLogic'

export function TileCanvas(): JSX.Element {
    const { logicProps } = useValues(workflowLogic)
    return (
        <BindLogic logic={tileCanvasLogic} props={logicProps}>
            <TileCanvasContent />
        </BindLogic>
    )
}
