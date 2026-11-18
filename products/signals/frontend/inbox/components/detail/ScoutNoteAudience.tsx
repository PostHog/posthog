import { useValues } from 'kea'

import { reportNoteAudience, reportNotesLogic } from '../../logics/reportNotesLogic'

/** "For <scout>" or "For every scout", using the scout's display name once the fleet has loaded. */
export function ScoutNoteAudience({ reportId, skillName }: { reportId: string; skillName: string }): JSX.Element {
    const { scoutNamesBySkill } = useValues(reportNotesLogic({ reportId }))
    return <>{reportNoteAudience(skillName, scoutNamesBySkill)}</>
}
