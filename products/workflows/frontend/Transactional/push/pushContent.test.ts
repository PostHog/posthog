import { EMPTY_PUSH_DRAFT, pushContentFrom, pushDataError, pushDraftFrom, variablesInPush } from './pushContent'

describe('pushContent', () => {
    it('reads back what it saves, so a saved push shows no unsaved changes', () => {
        const draft = {
            title: 'Order {{ variables.order_id }}',
            body: 'Shipped',
            image: '',
            link: 'myapp://orders',
            data: '{\n  "order_id": "{{ variables.order_id }}"\n}',
            channels: [3, 7],
        }

        expect(pushDraftFrom(pushContentFrom(draft))).toEqual(draft)
    })

    it.each([
        ['empty data', '', null],
        ['an object of strings', '{"a": "1"}', null],
        ['invalid JSON', '{"a": ', 'Enter valid JSON, like {"order_id": "{{ variables.order_id }}"}.'],
        ['a list', '["a"]', 'Enter a JSON object of keys and values.'],
        ['a number value', '{"a": 1}', 'Each value must be a string, because Firebase only delivers string values.'],
    ])('checks %s', (_name, data, expected) => {
        expect(pushDataError(data)).toEqual(expected)
    })

    it('lists the variables a push reads anywhere, once each, in order', () => {
        expect(
            variablesInPush({
                ...EMPTY_PUSH_DRAFT,
                title: 'Hi {{ variables.first_name }}',
                body: '{% if variables.vip %}VIP{% endif %} {{ variables.first_name }}',
                link: 'myapp://orders/{{ variables.order_id }}',
                data: '{"ref": "{{ variables.ref | default: variables.fallback }}"}',
            })
        ).toEqual(['first_name', 'vip', 'order_id', 'ref', 'fallback'])
    })
})
