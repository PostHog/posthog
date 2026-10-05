import { useActions, useValues } from 'kea'

import { Link } from '@posthog/lemon-ui'

import { pluralize } from 'lib/utils/strings'

import { recipientsLogic } from './recipientsLogic'
import { unreachablePersonsUrl } from './unreachablePersonsUrl'

const MIDDLE_MOUSE_BUTTON = 1

export function UnreachablePersonsNotice(): JSX.Element | null {
    const { personsWithoutEmail } = useValues(recipientsLogic)
    const { openUnreachablePersons } = useActions(recipientsLogic)

    if (personsWithoutEmail === 0) {
        return null
    }

    const openedWithMiddleButton = (event: React.MouseEvent): void => {
        if (event.button === MIDDLE_MOUSE_BUTTON) {
            openUnreachablePersons()
        }
    }

    return (
        <p className="text-xs text-secondary m-0">
            <span onClickCapture={openUnreachablePersons} onAuxClick={openedWithMiddleButton}>
                <Link to={unreachablePersonsUrl()} data-attr="audience-unreachable-persons">
                    {`${pluralize(personsWithoutEmail, 'person')} can't be reached`}
                </Link>
            </span>
            <span> because they have no email property.</span>
        </p>
    )
}
