import { initKeaTests } from '~/test/init'

import { sourceConnectionGroupsLogic } from './sourceConnectionGroupsLogic'

describe('sourceConnectionGroupsLogic', () => {
    beforeEach(() => {
        initKeaTests()
    })

    it.each([
        ['opens the first group before any toggle', null, ['GoogleAds', 'MetaAds'], [], ['GoogleAds']],
        [
            'opens every group that needs action before any toggle',
            null,
            ['GoogleAds', 'MetaAds', 'OpenAIAds'],
            ['OpenAIAds', 'MetaAds'],
            ['MetaAds', 'OpenAIAds'],
        ],
        [
            'opens a new integration when only stale groups were open',
            { expanded: ['BingAds'], seen: ['BingAds'] },
            ['GoogleAds'],
            [],
            ['GoogleAds'],
        ],
        [
            'opens a new integration after the user collapsed every group',
            { expanded: [], seen: ['BingAds'] },
            ['GoogleAds'],
            [],
            ['GoogleAds'],
        ],
        [
            'keeps every group closed when the user collapsed them',
            { expanded: [], seen: ['GoogleAds', 'MetaAds'] },
            ['GoogleAds', 'MetaAds'],
            [],
            [],
        ],
        [
            'drops stale groups and keeps the open ones',
            { expanded: ['BingAds', 'MetaAds'], seen: ['BingAds', 'GoogleAds', 'MetaAds'] },
            ['GoogleAds', 'MetaAds'],
            [],
            ['MetaAds'],
        ],
    ])('%s', (_, persisted, sourceTypes, sourceTypesNeedingAction, expected) => {
        const logic = sourceConnectionGroupsLogic({ expansionKey: 'test', sourceTypes, sourceTypesNeedingAction })
        logic.mount()
        if (persisted) {
            logic.actions.setExpandedSourceTypes(persisted.expanded, persisted.seen)
        }
        expect(logic.values.expandedSourceTypes).toEqual(expected)
    })
})
