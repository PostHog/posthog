import { useActions, useValues } from 'kea'

import { issueQueryOptionsLogic } from '../IssueQueryOptions/issueQueryOptionsLogic'
import { SeveritySelect } from './SeveritySelect'

export function SeverityFilter(): JSX.Element {
    const { severity } = useValues(issueQueryOptionsLogic)
    const { setSeverity } = useActions(issueQueryOptionsLogic)

    return <SeveritySelect severity={severity ?? null} onChange={setSeverity} />
}
