import { renderRouter } from 'expo-router/testing-library'
import type { ComponentType, ReactElement } from 'react'
import { View } from 'react-native'
import { FEATURE_FLAGS, type FeatureFlagKey, setFeatureFlags } from '@/lib/featureFlags'
import ErrorsTab from '../../../app/(tabs)/errors'
import ReplayTab from '../../../app/(tabs)/replay'
import IssueRoute from '../../../app/errors/[id]'
import ErrorsRoute from '../../../app/errors/index'
import SessionRoute from '../../../app/replay/[sessionId]'
import ReplayRoute from '../../../app/replay/index'

jest.mock('@/features/errors/ErrorsListScreen', () => ({ ErrorsListScreen: () => null }))
jest.mock('@/features/errors/IssueScreen', () => ({ IssueScreen: () => null }))
jest.mock('@/features/replay/ReplayListScreen', () => ({ ReplayListScreen: () => null }))
jest.mock('@/features/replay/SessionScreen', () => ({ SessionScreen: () => null }))
jest.mock('../settings/defaultPageStore', () => ({ currentDefaultPageHref: () => '/inbox' }))

function Inbox(): ReactElement {
    return <View />
}

const ROUTES: { path: string; url: string; component: ComponentType; flag: FeatureFlagKey }[] = [
    { path: 'errors/index', url: '/errors', component: ErrorsRoute, flag: FEATURE_FLAGS.errorTracking },
    { path: 'errors/[id]', url: '/errors/example-issue', component: IssueRoute, flag: FEATURE_FLAGS.errorTracking },
    { path: 'replay/index', url: '/replay', component: ReplayRoute, flag: FEATURE_FLAGS.sessionReplay },
    {
        path: 'replay/[sessionId]',
        url: '/replay/example-session',
        component: SessionRoute,
        flag: FEATURE_FLAGS.sessionReplay,
    },
    { path: '(tabs)/errors', url: '/(tabs)/errors', component: ErrorsTab, flag: FEATURE_FLAGS.errorTracking },
    { path: '(tabs)/replay', url: '/(tabs)/replay', component: ReplayTab, flag: FEATURE_FLAGS.sessionReplay },
]

describe('mobile product release gates', () => {
    afterEach(() => setFeatureFlags({}))

    test.each(ROUTES)('blocks $path unless its own flag is enabled', ({ path, url, component, flag }) => {
        const other = flag === FEATURE_FLAGS.errorTracking ? FEATURE_FLAGS.sessionReplay : FEATURE_FLAGS.errorTracking
        setFeatureFlags({ [other]: true })
        const app = renderRouter({ inbox: Inbox, [path]: component }, { initialUrl: url })
        expect(app.getPathname()).toBe('/inbox')
    })

    test.each(ROUTES)('opens $path with its flag enabled', ({ path, url, component, flag }) => {
        setFeatureFlags({ [flag]: true })
        const app = renderRouter({ inbox: Inbox, [path]: component }, { initialUrl: url })
        expect(app.getSegments().join('/')).toBe(path.replace('/index', ''))
    })
})
