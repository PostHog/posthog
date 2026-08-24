import { create } from "zustand";
import { persist } from "zustand/middleware";

interface ActiveRepoStoreState {
  path: string;
}

interface ActiveRepoStoreActions {
  setPath: (path: string) => void;
}

type ActiveRepoStore = ActiveRepoStoreState & ActiveRepoStoreActions;

export const useActiveRepoStore = create<ActiveRepoStore>()(
  persist(
    (set) => ({
      path: "",
      setPath: (path) => set({ path }),
    }),
    {
      name: "active-repo-store",
      partialize: (state) => ({ path: state.path }),
    },
  ),
);
