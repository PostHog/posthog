import { expectLogic } from 'kea-test-utils'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import type { SandboxCustomImageDTOApi } from 'products/tasks/frontend/generated/api.schemas'

import { MISSING_CUSTOM_IMAGE_LABEL, customImageChoices, signalsCustomImagesLogic } from './signalsCustomImagesLogic'

function image(id: string, overrides: Partial<SandboxCustomImageDTOApi> = {}): SandboxCustomImageDTOApi {
    return {
        id,
        name: `Image ${id}`,
        description: '',
        private: false,
        status: 'ready',
        version: 1,
        modal_image_name: '',
        error: '',
        ...overrides,
    }
}

describe('signalsCustomImagesLogic', () => {
    let logic: ReturnType<typeof signalsCustomImagesLogic.build> | null = null
    let requestedOrigins: (string | null)[]
    let response: [number, unknown]
    let visibleResponse: [number, unknown]

    beforeEach(() => {
        initKeaTests()
        requestedOrigins = []
        response = [200, { count: 0, results: [] }]
        visibleResponse = [200, { count: 0, results: [] }]
        useMocks({
            get: {
                '/api/projects/:id/sandbox_custom_images/': ({ request }) => {
                    const origin = new URL(request.url).searchParams.get('origin_product')
                    requestedOrigins.push(origin)
                    return origin === null ? visibleResponse : response
                },
            },
        })
    })

    afterEach(() => {
        logic?.unmount()
        logic = null
    })

    function mountWith(nextResponse: [number, unknown]): ReturnType<typeof signalsCustomImagesLogic.build> {
        response = nextResponse
        logic = signalsCustomImagesLogic({ origin: 'signal_report' })
        logic.mount()
        return logic
    }

    it('lists only shared, unarchived images for the origin', async () => {
        const mounted = mountWith([
            200,
            {
                count: 4,
                results: [
                    image('shared'),
                    image('building', { status: 'building' }),
                    image('private', { private: true }),
                    image('archived', { status: 'archived' }),
                ],
            },
        ])
        await expectLogic(mounted).toDispatchActions(['loadImagesSuccess'])
        expect(requestedOrigins).toEqual([null, 'signal_report'])
        expect(mounted.values.usableImages?.map((usable) => usable.id)).toEqual(['shared', 'building'])
        expect(mounted.values.imagesForbidden).toBe(false)
    })

    it('marks the list forbidden when the organization has no custom images', async () => {
        const mounted = mountWith([403, { detail: 'Custom images are not enabled.' }])
        await expectLogic(mounted).toDispatchActions(['loadImagesFailure'])
        expect(mounted.values.imagesForbidden).toBe(true)
        expect(
            customImageChoices(mounted.values.usableImages, mounted.values.imagesForbidden, 'saved', false)
        ).toBeNull()
    })

    test.each([
        { case: 'origin lists images', origin: [image('a')], visible: [image('a')], unsupported: false },
        { case: 'origin empty while images exist', origin: [], visible: [image('a')], unsupported: true },
        { case: 'no images anywhere', origin: [], visible: [], unsupported: false },
    ])('origin support: $case', async ({ origin, visible, unsupported }) => {
        visibleResponse = [200, { count: visible.length, results: visible }]
        const mounted = mountWith([200, { count: origin.length, results: origin }])
        await expectLogic(mounted).toDispatchActions(['loadImagesSuccess']).toFinishAllListeners()
        expect(mounted.values.originUnsupported).toBe(unsupported)
    })

    test.each([
        { case: 'loading', images: null, forbidden: false, saved: 'a', expected: null },
        { case: 'forbidden with a saved value', images: [image('a')], forbidden: true, saved: 'a', expected: null },
        { case: 'empty list and nothing saved', images: [], forbidden: false, saved: null, expected: null },
        { case: 'unsupported origin with a saved value', images: [], unsupported: true, saved: 'a', expected: null },
        { case: 'unsupported origin and nothing saved', images: [], unsupported: true, saved: null, expected: null },
        {
            case: 'empty list with a saved value',
            images: [],
            forbidden: false,
            saved: 'gone',
            expected: [{ value: 'gone', name: MISSING_CUSTOM_IMAGE_LABEL, status: null }],
        },
        {
            case: 'saved value no longer listed',
            images: [image('a')],
            forbidden: false,
            saved: 'gone',
            expected: [
                { value: 'a', name: 'Image a', status: null },
                { value: 'gone', name: MISSING_CUSTOM_IMAGE_LABEL, status: null },
            ],
        },
        {
            case: 'status shown only when not ready',
            images: [image('a'), image('b', { status: 'build_failed' })],
            forbidden: false,
            saved: 'a',
            expected: [
                { value: 'a', name: 'Image a', status: null },
                { value: 'b', name: 'Image b', status: { label: 'Build failed', type: 'danger' } },
            ],
        },
    ])('picker choices: $case', ({ images, forbidden = false, unsupported = false, saved, expected }) => {
        expect(customImageChoices(images, forbidden, saved, unsupported)).toEqual(expected)
    })
})
