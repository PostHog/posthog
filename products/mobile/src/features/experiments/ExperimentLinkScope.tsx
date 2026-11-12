import { type ReactElement, useMemo } from 'react'
import { View } from 'react-native'

import { ProjectScopeOverride, useSessionProjectScope } from '@/auth/projectScope'
import { useDataMode } from '@/demo/demoMode'
import { ViewChrome } from '@/features/views/screen/ViewChrome'
import { useViewBack } from '@/features/views/screen/ViewScreenFrame'
import { StateView } from '@/ui/StateView'

export function ExperimentLinkScope({
    project,
    host,
    children,
}: {
    project?: string
    host?: string
    children: ReactElement
}): ReactElement {
    const session = useSessionProjectScope()
    const demo = useDataMode() === 'demo'
    const goBack = useViewBack()
    const projectId = project && /^\d+$/.test(project) ? Number(project) : null
    const override = useMemo(
        () => (session && projectId !== null ? { host: session.host, projectId } : null),
        [session, projectId]
    )
    const elsewhere = !demo && session && host && new URL(session.host).host.toLowerCase() !== host.toLowerCase()
    if (elsewhere) {
        return (
            <View style={{ flex: 1 }}>
                <StateView
                    title="Sign in to open this experiment"
                    message="This link belongs to a different region or server. Sign in there, then open the link again."
                    actionLabel="Go back"
                    onAction={goBack}
                    testID="experiment-elsewhere"
                />
                <ViewChrome onBack={goBack} />
            </View>
        )
    }
    return <ProjectScopeOverride.Provider value={demo ? null : override}>{children}</ProjectScopeOverride.Provider>
}
