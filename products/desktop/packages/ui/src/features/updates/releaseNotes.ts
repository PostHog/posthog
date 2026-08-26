export interface CategorizedNotes {
  improved: string[];
  fixed: string[];
}

export interface ReleaseLike {
  name: string;
  version: string;
  notes: string;
  date: string | null;
  isPrerelease?: boolean;
}

export interface ReleaseGroup {
  key: string;
  label: string;
  releases: ReleaseLike[];
  isLatest: boolean;
}

// Recent releases stay broken out by day; anything older is bucketed by week so
// the timeline stays scannable when we ship a lot.
export const RECENT_DAYS = 3;
const DAY_MS = 86_400_000;

// Release notes are GitHub auto-generated: a "What's Changed" bullet list of PR
// titles (conventional-commit prefixed), plus contributor and "Full Changelog"
// noise. Keep only the change bullets, strip the prefix and "by @user in <pr>"
// attribution, and bucket `fix` into Fixed and everything else into Improved.
export function parseReleaseNotes(notes: string): CategorizedNotes {
  const improved: string[] = [];
  const fixed: string[] = [];
  for (const rawLine of notes.split("\n")) {
    const bullet = rawLine.trim().match(/^[-*•]\s+(.*)$/);
    if (!bullet) continue;
    let text = bullet[1].trim();
    if (text.startsWith("@")) continue; // "New Contributors" lines
    text = text.replace(/\s+by\s+@\S+\s+in\s+\S+.*$/i, "").trim();
    const conventional = text.match(/^([a-z]+)(?:\([^)]*\))?!?:\s*(.*)$/i);
    let isFix = false;
    if (conventional) {
      isFix = conventional[1].toLowerCase() === "fix";
      text = conventional[2].trim();
    } else {
      isFix = /^fix(ed|es)?\b/i.test(text);
    }
    if (text.length === 0) continue;
    text = text.charAt(0).toUpperCase() + text.slice(1);
    (isFix ? fixed : improved).push(text);
  }
  return { improved, fixed };
}

export function mergeReleaseNotes(releases: ReleaseLike[]): CategorizedNotes {
  const improved: string[] = [];
  const fixed: string[] = [];
  for (const release of releases) {
    const parsed = parseReleaseNotes(release.notes);
    improved.push(...parsed.improved);
    fixed.push(...parsed.fixed);
  }
  return {
    improved: Array.from(new Set(improved)),
    fixed: Array.from(new Set(fixed)),
  };
}

function dayLabel(date: Date): string {
  return date.toLocaleDateString(undefined, {
    year: "numeric",
    month: "long",
    day: "numeric",
  });
}

function mondayOf(date: Date): Date {
  const monday = new Date(date);
  monday.setDate(date.getDate() - ((date.getDay() + 6) % 7));
  return monday;
}

function weekLabel(date: Date): string {
  return `Week of ${mondayOf(date).toLocaleDateString(undefined, {
    month: "short",
    day: "numeric",
  })}`;
}

function weekKey(date: Date): string {
  return `week-${mondayOf(date).toDateString()}`;
}

// Groups newest-first releases: each of the last `recentDays` days is its own
// group; everything older is grouped into its calendar week.
export function groupReleases(
  releases: ReleaseLike[],
  now: number = Date.now(),
  recentDays: number = RECENT_DAYS,
): ReleaseGroup[] {
  const recentCutoff = now - recentDays * DAY_MS;
  const map = new Map<string, ReleaseGroup>();
  // The "Latest" badge should mark the newest stable release, not a prerelease
  // that sorts first; UpdateAvailableModal applies the same skip-prerelease rule.
  let latestStableGroup: ReleaseGroup | undefined;

  for (const release of releases) {
    const time = release.date ? Date.parse(release.date) : Number.NaN;
    const dated = !Number.isNaN(time);
    let key: string;
    let label: string;
    if (dated && time >= recentCutoff) {
      const date = new Date(time);
      key = `day-${date.toDateString()}`;
      label = dayLabel(date);
    } else if (dated) {
      const date = new Date(time);
      key = weekKey(date);
      label = weekLabel(date);
    } else {
      key = "earlier";
      label = "Earlier";
    }

    let group = map.get(key);
    if (!group) {
      group = { key, label, releases: [], isLatest: false };
      map.set(key, group);
    }
    group.releases.push(release);
    if (!latestStableGroup && !release.isPrerelease) {
      latestStableGroup = group;
    }
  }

  const groups = Array.from(map.values());
  const latestGroup = latestStableGroup ?? groups[0];
  if (latestGroup) {
    latestGroup.isLatest = true;
  }
  return groups;
}
