import { useActions, useValues } from 'kea'

import { Link } from '@posthog/lemon-ui'

import { pluralize } from 'lib/utils/strings'

import { recipientsLogic } from './recipientsLogic'
import { unreachablePersonsUrl } from './unreachablePersonsUrl'

export function UnreachablePersonsNotice(): JSX.Element | null {
    const { personsWithoutEmail } = useValues(recipientsLogic)
    const { openUnreachablePersons } = useActions(recipientsLogic)

    if (personsWithoutEmail === 0) {
        return null
    }

    return (
        <p className="text-xs text-secondary m-0">
            <Link
                to={unreachablePersonsUrl()}
                onClick={openUnreachablePersons}
                data-attr="audience-unreachable-persons"
            >{`${pluralize(personsWithoutEmail, 'person')} can't be reached`}</Link>
            <span> because they have no email property.</span>
        </p>
    )
}
