import type { TaskBrowserPermissionRequest } from "@posthog/platform/task-browser";
import { create } from "zustand";

interface TaskBrowserPermissionState {
  queue: TaskBrowserPermissionRequest[];
  enqueue: (request: TaskBrowserPermissionRequest) => void;
  remove: (requestId: string) => void;
}

export const useTaskBrowserPermissionStore =
  create<TaskBrowserPermissionState>()((set) => ({
    queue: [],
    enqueue: (request) =>
      set((state) => ({ queue: [...state.queue, request] })),
    remove: (requestId) =>
      set((state) => ({
        queue: state.queue.filter((request) => request.requestId !== requestId),
      })),
  }));
