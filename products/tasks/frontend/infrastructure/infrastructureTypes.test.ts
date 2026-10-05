import {
    CustomImage,
    Source,
    SourceData,
    Sources,
    customState,
    devStackState,
    imageState,
    pinState,
    releaseBadge,
} from './infrastructureTypes'

const image: CustomImage = {
    id: '00000000-0000-4000-8000-000000000001',
    team_id: 1,
    status: 'ready',
    version: 2,
    base_image_reference: 'old',
    base_image_refresh_reference: null,
    has_published_image: true,
    has_error: false,
    has_spec: true,
    updated_at: '2026-01-01T00:00:00Z',
    workflow_url: 'https://example.com/workflow',
}

describe('infrastructure rollout evidence', () => {
    it.each([
        ['current', 'ok', 'ok', 0, 'current'],
        ['previous', 'ok', 'ok', 0, 'waiting'],
        [null, 'ok', 'ok', 0, 'unknown'],
        ['current', 'error', 'ok', 0, 'unknown'],
        ['current', 'ok', 'error', 0, 'unknown'],
        ['current', 'ok', 'ok', 300_000, 'unknown'],
    ] as const)(
        'compares the baked base %s with fresh VM evidence (%s, %s, %s)',
        (base, devStatus, vmStatus, age, expected) => {
            const observed_at = new Date(Date.now() - age).toISOString()
            expect(
                devStackState({
                    dev_stack: {
                        status: devStatus,
                        observed_at,
                        data: {
                            name: 'example',
                            base_image_reference: base,
                            workflow_url: 'https://example.com/workflow',
                        },
                    },
                    vm: { status: vmStatus, observed_at, data: { name: 'vm', reference: 'current', platforms: [] } },
                })
            ).toEqual(expected)
        }
    )

    it.each([
        ['matching', ['1.1.0', '1.1.0'], 'ok', 0, 'Latest release', 'success'],
        ['different', ['1.0.0', '1.0.0'], 'ok', 0, 'Different release', 'warning'],
        ['mixed architectures', ['1.1.0', '1.0.0'], 'ok', 0, 'Different release', 'warning'],
        ['missing version label', ['1.1.0', null], 'ok', 0, 'Last seen', 'default'],
        ['missing architecture', ['1.1.0'], 'ok', 0, 'Last seen', 'default'],
        ['cached matching', ['1.1.0', '1.1.0'], 'error', 0, 'Last seen · matches latest', 'default'],
        ['cached different', ['1.0.0', '1.0.0'], 'error', 0, 'Last seen · differs from latest', 'warning'],
        ['stale matching', ['1.1.0', '1.1.0'], 'ok', 300_000, 'Last seen · matches latest', 'default'],
    ] as const)('labels %s observed releases without requiring GitHub', (_, versions, status, age, label, variant) => {
        const sources: Sources = {
            package: {
                status: 'ok',
                observed_at: new Date().toISOString(),
                data: { version: '1.1.0', revision: null },
            },
            base: {
                status,
                observed_at: new Date(Date.now() - age).toISOString(),
                data: {
                    name: 'base',
                    reference: 'example',
                    platforms: versions.map((version, index) => ({
                        arch: ['amd64', 'arm64'][index],
                        version,
                        revision: null,
                        base_revision: null,
                        inputs_digest: null,
                        digest: 'sha256:example',
                    })),
                },
            },
        }
        expect(releaseBadge(sources, 'base')).toEqual({ label, variant })
        expect(imageState(sources, 'base')).toEqual('unknown')
        sources.package!.status = 'error'
        expect(releaseBadge(sources, 'base')?.variant).not.toEqual('success')
        delete sources.base
        expect(releaseBadge(sources, 'base')).toBeUndefined()
    })

    it.each([
        [{}, 'waiting'],
        [{ has_error: true }, 'failed'],
        [{ base_image_reference: 'current' }, 'current'],
        [{ base_image_reference: null }, 'unknown'],
        [{ status: 'building', base_image_refresh_reference: 'current' }, 'building'],
        [{ has_spec: false }, 'unmanaged'],
        [{ has_published_image: false }, 'unmanaged'],
    ] as const)('classifies custom image %j as %s', (changes, expected) => {
        expect(customState({ ...image, ...changes }, 'current')).toEqual(expected)
    })

    it.each(['notebook', 'streamlit', 'pi', 'autoresearch', 'vm'] as const)(
        'requires matching lineage on both platforms and fresh evidence for %s',
        (name) => {
            const observed_at = new Date().toISOString()
            const platforms = ['amd64', 'arm64'].map((arch) => ({
                arch,
                version: '1.0.0',
                revision: 'base-revision',
                base_revision: 'base-revision',
                inputs_digest: 'inputs',
                digest: `sha256:${arch}`,
            }))
            const sources: Sources = {
                release: { status: 'ok', observed_at, data: { pin: '1.0.0', runs: [] } },
                base: { status: 'ok', observed_at, data: { name: 'base', reference: 'base', platforms } },
                [name]: {
                    status: 'ok',
                    observed_at,
                    data: { name, reference: name, platforms: structuredClone(platforms) },
                },
            }
            expect(imageState(sources, name)).toEqual('current')
            sources[name]!.data!.platforms[1].inputs_digest = 'old-inputs'
            expect(imageState(sources, name)).toEqual('waiting')
            sources[name]!.data!.platforms[1].inputs_digest = 'inputs'
            sources[name]!.data!.platforms[1].base_revision = 'old-base'
            expect(imageState(sources, name)).toEqual('waiting')
            sources[name]!.data!.platforms[1].base_revision = 'base-revision'
            sources.base!.status = 'error'
            expect(imageState(sources, name)).toEqual('unknown')
        }
    )

    it.each([
        ['1.0.0', '1.0.0', 'current'],
        ['1.1.0', '1.0.0', 'waiting'],
        ['', '1.0.0', 'unknown'],
        ['1.0.0', '', 'unknown'],
    ] as const)('compares package %s with pin %s', (version, pin, expected) => {
        const observed_at = new Date().toISOString()
        expect(
            pinState({
                package: { status: 'ok', observed_at, data: { version, revision: null } },
                release: { status: 'ok', observed_at, data: { pin, runs: [] } },
            })
        ).toEqual(expected)
    })

    it.each(['package', 'release'] as const)('requires fresh %s evidence for the pin', (name) => {
        const observed_at = new Date().toISOString()
        const sources: Sources = {
            package: { status: 'ok', observed_at, data: { version: '1.0.0', revision: null } },
            release: { status: 'ok', observed_at, data: { pin: '1.0.0', runs: [] } },
        }
        const source = sources[name] as Source<SourceData[typeof name]>
        source.observed_at = new Date(Date.now() - 300_000).toISOString()
        expect(pinState(sources)).toEqual('unknown')
        source.observed_at = observed_at
        source.status = 'error'
        expect(pinState(sources)).toEqual('unknown')
        delete sources[name]
        expect(pinState(sources)).toEqual('unknown')
    })
})
