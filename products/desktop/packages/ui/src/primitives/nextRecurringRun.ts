export type RecurringScheduleFrequency =
  | "hourly"
  | "daily"
  | "weekdays"
  | "weekly";

export interface RecurringSchedule {
  frequency: RecurringScheduleFrequency;
  time: string;
  weekday: string;
}

export function nextRecurringRun(
  schedule: RecurringSchedule,
  timezone: string,
  now = new Date(),
): Date | null {
  let formatter: Intl.DateTimeFormat;
  try {
    formatter = new Intl.DateTimeFormat("en-US", {
      timeZone: timezone,
      hourCycle: "h23",
      hour: "2-digit",
      minute: "2-digit",
      weekday: "short",
    });
  } catch {
    return null;
  }

  const weekdayNumbers: Record<string, string> = {
    Sun: "0",
    Mon: "1",
    Tue: "2",
    Wed: "3",
    Thu: "4",
    Fri: "5",
    Sat: "6",
  };
  const [targetHour, targetMinute] = schedule.time.split(":").map(Number);
  let candidateMs = Math.floor(now.getTime() / 60_000) * 60_000 + 60_000;

  for (let iteration = 0; iteration < 8 * 24 + 2; iteration += 1) {
    const parts = Object.fromEntries(
      formatter
        .formatToParts(new Date(candidateMs))
        .filter(({ type }) => type !== "literal")
        .map(({ type, value }) => [type, value]),
    );
    const minuteAdjustment = (targetMinute - Number(parts.minute) + 60) % 60;
    if (minuteAdjustment > 0) {
      candidateMs += minuteAdjustment * 60_000;
      continue;
    }

    const weekday = weekdayNumbers[parts.weekday];
    const matchesHour =
      schedule.frequency === "hourly" || Number(parts.hour) === targetHour;
    const matchesWeekday =
      schedule.frequency !== "weekdays" || (weekday !== "0" && weekday !== "6");
    const matchesWeekly =
      schedule.frequency !== "weekly" || weekday === schedule.weekday;
    if (matchesHour && matchesWeekday && matchesWeekly) {
      return new Date(candidateMs);
    }
    candidateMs += 60 * 60_000;
  }

  return null;
}
