import type { PermissionOption } from '../types/wireTypes'
import { mapPermissionOption, mapPermissionOptions } from './permissionUtils'

describe('permissionUtils', () => {
    describe('mapPermissionOption', () => {
        it.each<[string, Partial<ReturnType<typeof mapPermissionOption>>]>([
            [
                'allow_once',
                {
                    decision: 'approved',
                    primary: true,
                    remembered: false,
                    requiresFeedback: false,
                    supportsFeedback: false,
                },
            ],
            ['allow_always', { decision: 'approved', primary: false, remembered: true }],
            ['reject', { decision: 'declined', primary: false, requiresFeedback: false, supportsFeedback: false }],
            ['reject_with_feedback', { decision: 'declined', requiresFeedback: true, supportsFeedback: false }],
        ])('maps the known kind %s onto the card model', (kind, expected) => {
            expect(mapPermissionOption({ optionId: 'x', name: '', kind })).toMatchObject(expected)
        })

        it('treats reject_once as a one-click decline that supports optional feedback via customInput', () => {
            expect(
                mapPermissionOption({ optionId: 'r', name: 'No', kind: 'reject_once', customInput: true })
            ).toMatchObject({
                decision: 'declined',
                requiresFeedback: false,
                supportsFeedback: true,
            })
            // Without customInput it is still a plain decline, just no feedback field.
            expect(mapPermissionOption({ optionId: 'r', name: 'No', kind: 'reject_once' })).toMatchObject({
                decision: 'declined',
                requiresFeedback: false,
                supportsFeedback: false,
            })
        })

        it.each([
            ['allow_for_session', 'approved'],
            ['deny_forever', 'declined'],
        ])('classifies the unknown kind %s by prefix instead of dropping it', (kind, decision) => {
            expect(mapPermissionOption({ optionId: 'x', name: '', kind }).decision).toEqual(decision)
        })

        it.each([
            ['allow_once', 'Approve'],
            ['allow_always', 'Approve always'],
            ['reject_once', 'Decline'],
            ['reject_with_feedback', 'Decline with feedback…'],
        ])('falls back to a default label for %s when the wire omits a name', (kind, label) => {
            expect(mapPermissionOption({ optionId: 'a', name: '', kind }).label).toEqual(label)
        })
    })

    describe('mapPermissionOptions', () => {
        it('hides allow_always unless the tool preview opts into remembering', () => {
            const options: PermissionOption[] = [
                { optionId: 'a', name: '', kind: 'allow_once' },
                { optionId: 'd', name: '', kind: 'allow_always' },
            ]
            expect(mapPermissionOptions(options).map((o) => o.optionId)).toEqual(['a'])
            expect(mapPermissionOptions(options, true).map((o) => o.optionId)).toEqual(['a', 'd'])
        })
    })
})
