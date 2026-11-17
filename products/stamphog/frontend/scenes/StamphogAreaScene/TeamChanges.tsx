import { AreaFilters } from './AreaFilters'
import { AreaList } from './AreaList'

/** The Team changes tab of Code review: what changed in code a team owns, and whether the team saw it before it merged. */
export function TeamChanges(): JSX.Element {
    return (
        <>
            <AreaFilters />
            <AreaList />
        </>
    )
}
