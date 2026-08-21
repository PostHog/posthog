import type { ReactNode } from "react";
import { create } from "zustand";

interface HeaderStore {
  content: ReactNode;
  setContent: (content: ReactNode) => void;
}

export const useHeaderStore = create<HeaderStore>((set) => ({
  content: null,
  setContent: (content) => set({ content }),
}));
