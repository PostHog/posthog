import { create } from "zustand";

interface AllUsersTaskPollState {
  observers: number;
  register: () => void;
  unregister: () => void;
}

export const useAllUsersTaskPollStore = create<AllUsersTaskPollState>()(
  (set) => ({
    observers: 0,
    register: () => set((state) => ({ observers: state.observers + 1 })),
    unregister: () =>
      set((state) => ({ observers: Math.max(0, state.observers - 1) })),
  }),
);
