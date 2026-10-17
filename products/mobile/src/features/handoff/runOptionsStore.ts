import { create } from 'zustand'

import type { PermissionModeApi, RuntimeAdapterApi } from '@/api/tasks'
import { addSessionEndTask, useAuthStore } from '@/auth/authStore'

import { DEFAULT_RUN_OPTIONS, type PinnedModel, type RunOptions, resolveModeForRuntimeAdapter } from './runOptions'

interface RunOptionsState {
    options: RunOptions
    /** `runtimeAdapter` is the harness the run lands on, so a mode from the other harness is mapped onto it. */
    setModel: (model: PinnedModel | 'default', runtimeAdapter: RuntimeAdapterApi) => void
    setPermissionMode: (mode: PermissionModeApi) => void
    setBranch: (branch: string) => void
    reset: () => void
}

// In memory for one sheet session, like the web's per-run picks: it resets when the hand-off sheet closes and after a
// hand-off, so the quick button never sends picks made on another report.
export const useRunOptionsStore = create<RunOptionsState>()((set) => ({
    options: DEFAULT_RUN_OPTIONS,
    setModel: (model, runtimeAdapter) =>
        set((state) => ({
            options: {
                ...state.options,
                model,
                permissionMode: resolveModeForRuntimeAdapter(runtimeAdapter, state.options.permissionMode),
            },
        })),
    setPermissionMode: (permissionMode) => set((state) => ({ options: { ...state.options, permissionMode } })),
    setBranch: (branch) => set((state) => ({ options: { ...state.options, branch } })),
    reset: () => set({ options: DEFAULT_RUN_OPTIONS }),
}))

addSessionEndTask(() => useRunOptionsStore.getState().reset())

// A branch or model picked in one project means nothing in another.
useAuthStore.subscribe((state, previous) => {
    if (state.projectId !== previous.projectId) {
        useRunOptionsStore.getState().reset()
    }
})
