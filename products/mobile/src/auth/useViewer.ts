import { DEMO_PROJECT_NAME } from '@/demo/briefings'
import { useDemoMode } from '@/demo/demoMode'
import { DEMO_ME } from '@/demo/fixtures'

import { useAuthStore } from './authStore'

export interface Viewer {
    name: string
    projectName: string
}

export function useViewer(): Viewer {
    const demo = useDemoMode((state) => state.enabled)
    const projectName = useAuthStore((state) => state.projectName)
    const name = useAuthStore((state) => state.user?.name)
    if (demo) {
        return { name: DEMO_ME.name, projectName: DEMO_PROJECT_NAME }
    }
    return { name: name ?? '', projectName: projectName ?? '' }
}
