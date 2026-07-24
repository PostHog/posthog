import {
  advance as advanceMachine,
  completeTour as completeTourMachine,
  computeReturningUserMigration,
  dismiss as dismissMachine,
  startTour as startTourMachine,
  type TourEvent,
} from "@posthog/core/tour/tourMachine";
import { getRegisteredTours, getTour } from "@posthog/core/tour/tourRegistry";
import { ANALYTICS_EVENTS } from "@posthog/shared/analytics-events";
import { track } from "@posthog/ui/shell/analytics";
import { create } from "zustand";
import { persist } from "zustand/middleware";

interface TourStoreState {
  completedTourIds: string[];
  activeTourId: string | null;
  activeStepIndex: number;
}

interface TourStoreActions {
  startTour: (tourId: string) => void;
  advance: (tourId: string, stepId: string) => void;
  completeTour: (tourId: string) => void;
  dismiss: () => void;
  resetTours: () => void;
  applyReturningUserMigration: (hasCompletedOnboarding: boolean) => void;
}

type TourStore = TourStoreState & TourStoreActions;

const RETURNING_USER_MIGRATION_KEY = "tour-store-v1-migrated";

function emit(events: TourEvent[]): void {
  for (const event of events) {
    track(ANALYTICS_EVENTS.TOUR_EVENT, event);
  }
}

export const useTourStore = create<TourStore>()(
  persist(
    (set, get) => ({
      completedTourIds: [],
      activeTourId: null,
      activeStepIndex: 0,

      startTour: (tourId) => {
        const { state, events } = startTourMachine(get(), tourId, getTour);
        set(state);
        emit(events);
      },

      advance: (tourId, stepId) => {
        const { state, events } = advanceMachine(
          get(),
          tourId,
          stepId,
          getTour,
        );
        set(state);
        emit(events);
      },

      completeTour: (tourId) => {
        const { state, events } = completeTourMachine(get(), tourId, getTour);
        set(state);
        emit(events);
      },

      dismiss: () => {
        const { state, events } = dismissMachine(get(), getTour);
        set(state);
        emit(events);
      },

      resetTours: () => {
        set({ completedTourIds: [], activeTourId: null, activeStepIndex: 0 });
      },

      applyReturningUserMigration: (hasCompletedOnboarding) => {
        if (localStorage.getItem(RETURNING_USER_MIGRATION_KEY)) return;
        localStorage.setItem(RETURNING_USER_MIGRATION_KEY, "1");

        const ids = computeReturningUserMigration(
          getRegisteredTours(),
          hasCompletedOnboarding,
        );
        for (const id of ids) {
          get().completeTour(id);
        }
      },
    }),
    {
      name: "tour-store",
      partialize: (state) => ({
        completedTourIds: state.completedTourIds,
      }),
    },
  ),
);
