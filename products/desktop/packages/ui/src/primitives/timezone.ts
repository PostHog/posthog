export interface TimezoneOption {
  value: string;
  label: string;
}

let cachedTimezoneOptions: TimezoneOption[] | null = null;
let timezoneOptionsExpireAt = 0;
const scheduleTimestampFormatters = new Map<string, Intl.DateTimeFormat>();

export function systemTimezone(): string {
  try {
    return Intl.DateTimeFormat().resolvedOptions().timeZone || "UTC";
  } catch {
    return "UTC";
  }
}

export function formatTimezoneLabel(timezone: string): string {
  const name = timezone.replaceAll("_", " ").replaceAll("/", " / ");

  try {
    const offset = new Intl.DateTimeFormat("en-US", {
      timeZone: timezone,
      timeZoneName: "longOffset",
    })
      .formatToParts()
      .find((part) => part.type === "timeZoneName")
      ?.value.replace("GMT", "UTC");
    return offset ? `${name} (${offset})` : name;
  } catch {
    return name;
  }
}

export function formatTimezoneAbbreviation(
  timezone: string,
  date = new Date(),
): string {
  try {
    return (
      new Intl.DateTimeFormat("en-US", {
        timeZone: timezone,
        timeZoneName: "short",
      })
        .formatToParts(date)
        .find((part) => part.type === "timeZoneName")?.value ?? timezone
    );
  } catch {
    return timezone;
  }
}

export function formatTimestampInTimezone(
  date: Date,
  timezone: string,
): string {
  try {
    return new Intl.DateTimeFormat(undefined, {
      timeZone: timezone,
      weekday: "short",
      month: "short",
      day: "numeric",
      year: "numeric",
      hour: "numeric",
      minute: "2-digit",
    }).format(date);
  } catch {
    return date.toLocaleString();
  }
}

export function formatScheduleTimestamp(date: Date, timezone: string): string {
  try {
    let formatter = scheduleTimestampFormatters.get(timezone);
    if (!formatter) {
      formatter = new Intl.DateTimeFormat(undefined, {
        timeZone: timezone,
        weekday: "short",
        month: "short",
        day: "numeric",
        hour: "numeric",
        minute: "2-digit",
        timeZoneName: "short",
      });
      scheduleTimestampFormatters.set(timezone, formatter);
    }
    return formatter.format(date);
  } catch {
    return date.toLocaleString();
  }
}

export function isValidTimezone(timezone: string): boolean {
  try {
    new Intl.DateTimeFormat("en-US", { timeZone: timezone }).format();
    return true;
  } catch {
    return false;
  }
}

export function timezoneOptions(): TimezoneOption[] {
  if (cachedTimezoneOptions && Date.now() < timezoneOptionsExpireAt) {
    return cachedTimezoneOptions;
  }

  const localTimezone = systemTimezone();
  let timezones: string[];

  try {
    timezones = Intl.supportedValuesOf("timeZone");
  } catch {
    timezones = [];
  }

  cachedTimezoneOptions = [...new Set([localTimezone, "UTC", ...timezones])]
    .sort((left, right) => left.localeCompare(right))
    .map((timezone) => ({
      value: timezone,
      label: formatTimezoneLabel(timezone),
    }));
  timezoneOptionsExpireAt = Date.now() + 60 * 60 * 1000;
  return cachedTimezoneOptions;
}
