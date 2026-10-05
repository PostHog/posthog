import { useActions, useValues } from 'kea'

import { Link } from '@posthog/lemon-ui'

import { recipientsLogic } from './recipientsLogic'
import { unreachablePersonsUrl } from './unreachablePersonsUrl'

export function UnreachablePersonsNotice(): JSX.Element | null {
    const { personsWithoutEmail } = useValues(recipientsLogic)
    const { openUnreachablePersons } = useActions(recipientsLogic)

    if (personsWithoutEmail === 0) {
        return null
    }

    const subject = personsWithoutEmail === 1 ? '1 person' : `${personsWithoutEmail.toLocaleString()} persons`
    return (
        <p className="text-xs text-secondary m-0">
            <Link
                to={unreachablePersonsUrl()}
                onClick={openUnreachablePersons}
                data-attr="audience-unreachable-persons"
            >{`${subject} can't be reached`}</Link>
            <span> because they have no email property.</span>
        </p>
    )
}
