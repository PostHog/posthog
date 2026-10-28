import { useActions, useValues } from 'kea'

import { workflowLogic } from '../../../workflowLogic'
import { WorkflowRevisions } from '../../../WorkflowRevisions'
import { HogFlowEditorPanel } from '../../panel/HogFlowEditorPanel'
import { tileCanvasLogic } from './tileCanvasLogic'

export function TileCanvasPanel(): JSX.Element {
    const { isHistoryOpen } = useValues(tileCanvasLogic)
    const { closePanel } = useActions(tileCanvasLogic)
    const { logicProps } = useValues(workflowLogic)
    const historyView =
        isHistoryOpen && logicProps.id
            ? {
                  title: 'History',
                  content: (
                      <div className="min-h-0 flex-1 overflow-y-auto p-3">
                          <WorkflowRevisions id={logicProps.id} />
                      </div>
                  ),
              }
            : undefined
    return <HogFlowEditorPanel layout="docked" onClose={closePanel} view={historyView} />
}
