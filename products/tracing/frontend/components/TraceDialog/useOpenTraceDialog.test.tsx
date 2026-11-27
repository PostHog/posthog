import '@testing-library/jest-dom'

import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { Provider } from 'kea'
import { router } from 'kea-router'

import { traceDialogOpenLogic } from 'lib/components/ViewTraceButton/traceDialogOpenLogic'
import { ViewTraceButton } from 'lib/components/ViewTraceButton/ViewTraceButton'

import { initKeaTests } from '~/test/init'
import { AccessControlLevel, AccessControlResourceType, AppContext } from '~/types'

import { useOpenTraceDialog } from './useOpenTraceDialog'

function DialogTraceButton(): JSX.Element | null {
    const openTraceDialog = useOpenTraceDialog()
    return (
        <ViewTraceButton
            traceId="abc123"
            spanId="def456"
            onClick={(event) =>
                openTraceDialog(event, { traceId: 'abc123', spanId: 'def456' }, { entryPoint: 'log_details' })
            }
        />
    )
}

describe('useOpenTraceDialog', () => {
    beforeEach(() => {
        window.POSTHOG_APP_CONTEXT = {
            ...window.POSTHOG_APP_CONTEXT,
            resource_access_control: {
                ...window.POSTHOG_APP_CONTEXT?.resource_access_control,
                [AccessControlResourceType.Tracing]: AccessControlLevel.Viewer,
            },
        } as AppContext
        initKeaTests()
    })

    afterEach(() => cleanup())

    it.each([
        ['a plain click', {}, true],
        // Modifier clicks skip the dialog and leave the link to go to Tracing.
        ['a cmd click', { metaKey: true }, false],
        ['a ctrl click', { ctrlKey: true }, false],
        ['a shift click', { shiftKey: true }, false],
    ])('%s opens the dialog: %s', (_name, modifiers, expectDialog) => {
        traceDialogOpenLogic.mount()
        router.actions.push('/logs')
        const pathnameBeforeClick = router.values.location.pathname

        render(
            <Provider>
                <DialogTraceButton />
            </Provider>
        )
        fireEvent.click(screen.getByText('View trace'), modifiers)

        expect(traceDialogOpenLogic.values.isOpen).toBe(expectDialog)
        if (expectDialog) {
            expect(traceDialogOpenLogic.values.trace).toMatchObject({ traceId: 'abc123', spanId: 'DEF456' })
            // A dialog click must not also follow the link.
            expect(router.values.location.pathname).toBe(pathnameBeforeClick)
        }
    })
})
