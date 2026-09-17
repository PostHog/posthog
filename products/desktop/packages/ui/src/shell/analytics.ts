import { resolveService } from "@posthog/di/container";
import type {
  EventPropertyMap,
  UserIdentifyProperties,
} from "@posthog/shared/analytics-events";
import type { Task } from "@posthog/shared/domain-types";

type TrackArgs<K extends keyof EventPropertyMap> =
  EventPropertyMap[K] extends never
    ? []
    : EventPropertyMap[K] extends undefined
      ? [properties?: EventPropertyMap[K]]
      : [properties: EventPropertyMap[K]];

export interface AnalyticsUserGroups {
  team?: { id: number; uuid: string; name: string } | null;
  organization?: { id: string; name: string; slug: string } | null;
}

export interface AnalyticsTracker {
  track<K extends keyof EventPropertyMap>(
    eventName: K,
    ...args: TrackArgs<K>
  ): void;
  setActiveTaskContext(task: Task | null): void;
  captureException(
    error: Error,
    additionalProperties?: Record<string, unknown>,
  ): void;
  identifyUser(userId: string, properties?: UserIdentifyProperties): void;
  setUserGroups(user: AnalyticsUserGroups): void;
  resetUser(): void;
  captureSurveyResponse(params: {
    surveyId: string;
    responses: Array<{ questionId: string; response: string }>;
  }): void;
}

export const ANALYTICS_TRACKER = Symbol.for("posthog.ui.AnalyticsTracker");

export function track<K extends keyof EventPropertyMap>(
  eventName: K,
  ...args: TrackArgs<K>
): void {
  resolveService<AnalyticsTracker>(ANALYTICS_TRACKER).track(eventName, ...args);
}

export function setActiveTaskContext(task: Task | null): void {
  resolveService<AnalyticsTracker>(ANALYTICS_TRACKER).setActiveTaskContext(
    task,
  );
}

export function captureException(
  error: Error,
  additionalProperties?: Record<string, unknown>,
): void {
  resolveService<AnalyticsTracker>(ANALYTICS_TRACKER).captureException(
    error,
    additionalProperties,
  );
}

export function identifyUser(
  userId: string,
  properties?: UserIdentifyProperties,
): void {
  resolveService<AnalyticsTracker>(ANALYTICS_TRACKER).identifyUser(
    userId,
    properties,
  );
}

export function setUserGroups(user: AnalyticsUserGroups): void {
  resolveService<AnalyticsTracker>(ANALYTICS_TRACKER).setUserGroups(user);
}

export function resetUser(): void {
  resolveService<AnalyticsTracker>(ANALYTICS_TRACKER).resetUser();
}

export function captureSurveyResponse(params: {
  surveyId: string;
  responses: Array<{ questionId: string; response: string }>;
}): void {
  resolveService<AnalyticsTracker>(ANALYTICS_TRACKER).captureSurveyResponse(
    params,
  );
}
