import '@testing-library/jest-dom'

import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { Provider } from 'kea'
import { router } from 'kea-router'

import { ViewTraceButton } from 'lib/components/ViewTraceButton/ViewTraceButton'
import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import { initKeaTests } from '~/test/init'
import { AccessControlLevel, AccessControlResourceType, AppContext } from '~/types'

import { traceDialogOpenLogic } from './traceDialogOpenLogic'
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
        ['a plain click with the flag on', true, {}, true],
        // Modifier clicks skip the dialog and leave the link to go to Tracing.
        ['a cmd click', true, { metaKey: true }, false],
        ['a ctrl click', true, { ctrlKey: true }, false],
        ['a shift click', true, { shiftKey: true }, false],
        ['a plain click with the flag off', false, {}, false],
    ])('%s opens the dialog: %s', (_name, flagOn, modifiers, expectDialog) => {
        featureFlagLogic.mount()
        featureFlagLogic.actions.setFeatureFlags([], { [FEATURE_FLAGS.TRACING_TRACE_DIALOG]: flagOn })
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
