import { colors } from "@posthog/brand/colors";
import { assets } from "@posthog/brand/hoggies/metadata";
import { hoggiePngUrl } from "@posthog/shared/announcements";

export interface Hoggie {
  /** PNG file stem — what goes into the payload and onto the CDN URL. */
  slug: string;
  name: string;
  tags: string[];
  /** CDN URL, pinned to the same release the file list came from. */
  src: string;
}

const metaByFileStem = new Map(
  assets.map((asset) => {
    const variant = Object.values(asset.variant ?? {})[0];
    return [variant ? `${asset.slug}-${variant}` : asset.slug, asset] as const;
  }),
);

function titleCase(stem: string): string {
  return stem.replace(/-/g, " ").replace(/\b[a-z]/g, (c) => c.toUpperCase());
}

// __HOGGIE_FILES__ lists the release's shipped PNGs (see vite.config.ts); the
// metadata manifest can't be the list itself — variants there share one slug
// (five "wizard" entries for files wizard-1..5.png) — so it only decorates
// files with display names and search tags.
export const hoggieCatalog: Hoggie[] = __HOGGIE_FILES__
  .map((stem) => {
    // Second lookup catches stem/slug drift like file 9-9-6.png ↔ slug "996".
    const meta =
      metaByFileStem.get(stem) ?? metaByFileStem.get(stem.replace(/-/g, ""));
    const variant = Object.values(meta?.variant ?? {})[0];
    const name = meta
      ? variant
        ? `${meta.name} ${variant}`
        : meta.name
      : titleCase(stem);
    return {
      slug: stem,
      name,
      tags: meta?.tags ?? [],
      src: hoggiePngUrl(stem),
    };
  })
  .sort((a, b) => a.name.localeCompare(b.name));

/** Hero band background presets, straight from the brand color tokens. */
export const BAND_COLORS: { name: string; hex: string }[] = Object.values(
  colors,
).map((color) => ({ name: color.name, hex: color.core.toLowerCase() }));
