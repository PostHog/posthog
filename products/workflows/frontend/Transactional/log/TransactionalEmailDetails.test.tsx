import '@testing-library/jest-dom'

import { cleanup, render, screen } from '@testing-library/react'
import { Provider } from 'kea'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import { initKeaTests } from '~/test/init'

import type { TransactionalEmailLogDetailApi } from 'products/messaging/frontend/generated/api.schemas'

import { TransactionalEmailDetails } from './TransactionalEmailDetails'

const send = (
    email: Pick<TransactionalEmailLogDetailApi, 'code_email_id' | 'template_id'>
): TransactionalEmailLogDetailApi =>
    ({
        message_id: 'msg-1',
        created_at: '2026-03-14T10:00:00Z',
        status: 'delivered',
        recipient: 'ada@example.com',
        template_name: 'Password reset',
        ...email,
    }) as TransactionalEmailLogDetailApi

describe('TransactionalEmailDetails', () => {
    afterEach(cleanup)

    it.each([
        [
            'a code send links to its code email',
            true,
            { code_email_id: 'code-1', template_id: null },
            '/transactional/code-emails/code-1',
        ],
        [
            'a template send links to its template',
            true,
            { code_email_id: null, template_id: 'tpl-1' },
            '/transactional/library/templates/tpl-1',
        ],
        ['without the flag, a code send links nowhere', false, { code_email_id: 'code-1', template_id: null }, null],
        [
            'without the flag, a template send links to its template',
            false,
            { code_email_id: null, template_id: 'tpl-1' },
            '/transactional/library/templates/tpl-1',
        ],
    ])('%s', (_name, sendLinks, email, href) => {
        initKeaTests()
        featureFlagLogic.mount()
        featureFlagLogic.actions.setFeatureFlags(sendLinks ? [FEATURE_FLAGS.WORKFLOWS_EMAIL_SEND_LINKS] : [], {
            [FEATURE_FLAGS.WORKFLOWS_EMAIL_SEND_LINKS]: sendLinks,
        })
        render(
            <Provider>
                <TransactionalEmailDetails email={send(email)} />
            </Provider>
        )

        const link = screen.getByText('Password reset').closest('a')
        if (href) {
            expect(link?.getAttribute('href')).toMatch(new RegExp(`${href}$`))
        } else {
            expect(link).toBeNull()
        }
    })
})
