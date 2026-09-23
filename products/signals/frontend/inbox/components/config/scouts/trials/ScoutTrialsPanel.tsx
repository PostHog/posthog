import { useActions, useAllValues } from 'kea'

import { ScoutTrialsLogicProps, scoutTrialsLogic } from '../../../../logics/scoutTrialsLogic'
import { ScoutTrialsView } from './ScoutTrialsView'

export function ScoutTrialsPanel(props: ScoutTrialsLogicProps): JSX.Element {
    const logic = scoutTrialsLogic(props)
    const values = useAllValues(logic)
    const actions = useActions(logic)

    return <ScoutTrialsView {...values} {...actions} />
}
