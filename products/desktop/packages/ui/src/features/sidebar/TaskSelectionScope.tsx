import {
  createTaskSelectionStore,
  type TaskSelectionStoreHook,
  useTaskSelectionStore,
} from "@posthog/ui/features/sidebar/taskSelectionStore";
import { createContext, type ReactNode, useContext, useState } from "react";

const TaskSelectionStoreContext = createContext<TaskSelectionStoreHook>(
  useTaskSelectionStore,
);

export function TaskSelectionScope({ children }: { children: ReactNode }) {
  const [store] = useState(createTaskSelectionStore);
  return (
    <TaskSelectionStoreContext.Provider value={store}>
      {children}
    </TaskSelectionStoreContext.Provider>
  );
}

export function useScopedTaskSelectionStore(): TaskSelectionStoreHook {
  return useContext(TaskSelectionStoreContext);
}
