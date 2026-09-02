import { hoggiePngUrl } from "@posthog/shared/announcements";
import { useEffect, useMemo, useState } from "react";
import builderHog from "./assets/hedgehogs/builder-hog-03.png";
import explorerHog from "./assets/hedgehogs/explorer-hog.png";
import happyHog from "./assets/hedgehogs/happy-hog.png";
import loopHog from "./assets/hedgehogs/loop-hog.svg";
import { BAND_COLORS, hoggieCatalog } from "./hoggies";
import { type EditableItem, kindDefaultHedgehog } from "./items";

// The app-bundled default hedgehogs are not in the brand catalog; render them
// from the same local copies the app uses.
const APP_BUNDLED_SRC: Record<string, string> = {
  builder: builderHog,
  explorer: explorerHog,
  happy: happyHog,
  loop: loopHog,
};

/** App-bundled defaults render locally; everything else comes off the CDN. */
function hoggieSrc(slug: string): string {
  return APP_BUNDLED_SRC[slug] ?? hoggiePngUrl(slug);
}

type Patch = Partial<EditableItem>;
type OnChange = (patch: Patch) => void;

function defaultColor(kind: EditableItem["kind"]): string {
  return kind === "required-update" ? "#f54e00" : "#2f80fa";
}

function segCls(active: boolean): string {
  return active ? "seg-btn seg-btn-active" : "seg-btn";
}

function SunIcon() {
  return (
    <svg viewBox="0 0 16 16" aria-hidden="true">
      <circle cx="8" cy="8" r="2.5" />
      <path d="M8 1v2M8 13v2M1 8h2M13 8h2M3.05 3.05l1.4 1.4M11.55 11.55l1.4 1.4M12.95 3.05l-1.4 1.4M4.45 11.55l-1.4 1.4" />
    </svg>
  );
}

function MoonIcon() {
  return (
    <svg viewBox="0 0 16 16" aria-hidden="true">
      <path d="M13.25 10.25A5.75 5.75 0 0 1 5.75 2.75a5.75 5.75 0 1 0 7.5 7.5Z" />
    </svg>
  );
}

function GeometricPattern() {
  return (
    <svg
      className="st-pattern"
      viewBox="0 0 232 96"
      preserveAspectRatio="xMidYMid slice"
      aria-hidden="true"
    >
      <circle cx="26" cy="22" r="11" fill="currentColor" opacity="0.25" />
      <circle
        cx="204"
        cy="66"
        r="17"
        fill="none"
        stroke="currentColor"
        strokeWidth="3"
        opacity="0.3"
      />
      <rect
        x="176"
        y="10"
        width="15"
        height="15"
        rx="2"
        transform="rotate(18 183 17)"
        fill="currentColor"
        opacity="0.2"
      />
      <polygon points="64,10 75,30 53,30" fill="currentColor" opacity="0.3" />
      <path
        d="M8 62 l7 -8 7 8 7 -8 7 8"
        fill="none"
        stroke="currentColor"
        strokeWidth="2.5"
        strokeLinecap="round"
        strokeLinejoin="round"
        opacity="0.35"
      />
      <circle cx="118" cy="14" r="4" fill="currentColor" opacity="0.35" />
      <path
        d="M148 78 h12 M154 72 v12"
        stroke="currentColor"
        strokeWidth="3"
        strokeLinecap="round"
        opacity="0.3"
      />
      <circle
        cx="52"
        cy="78"
        r="6"
        fill="none"
        stroke="currentColor"
        strokeWidth="2.5"
        opacity="0.25"
      />
      <rect
        x="96"
        y="70"
        width="10"
        height="10"
        transform="rotate(-12 101 75)"
        fill="currentColor"
        opacity="0.18"
      />
      <polygon
        points="206,18 214,32 198,32"
        fill="none"
        stroke="currentColor"
        strokeWidth="2.5"
        strokeLinejoin="round"
        opacity="0.3"
      />
    </svg>
  );
}

function HeroBand({ item }: { item: EditableItem }) {
  if (item.heroType === "image") {
    return item.heroImageUrl ? (
      <div className="st-hero">
        <img className="st-hero-cover" src={item.heroImageUrl} alt="" />
        <div className="st-hero-fade" />
      </div>
    ) : (
      <div className="st-hero st-hero-blank">
        paste an image url in the toolbar
      </div>
    );
  }
  return (
    <div
      className="st-hero"
      style={{ backgroundColor: item.heroColor || defaultColor(item.kind) }}
    >
      <GeometricPattern />
      <img className="st-hero-hog" src={hoggieSrc(item.heroHedgehog)} alt="" />
      <div className="st-hero-fade" />
    </div>
  );
}

function HoggiePicker({
  item,
  onChange,
}: {
  item: EditableItem;
  onChange: OnChange;
}) {
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const active = item.heroType === "hedgehog";

  const results = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return hoggieCatalog;
    return hoggieCatalog.filter(
      (h) =>
        h.name.toLowerCase().includes(q) ||
        h.slug.includes(q) ||
        h.tags.some((t) => t.toLowerCase().includes(q)),
    );
  }, [query]);
  const defaultSlug = kindDefaultHedgehog(item.kind);

  return (
    <div className="hog-pick">
      <button
        type="button"
        className={active ? "hog-current hog-current-active" : "hog-current"}
        title="Pick a hedgehog for the hero band"
        onClick={() => {
          if (!active) onChange({ heroType: "hedgehog" });
          setOpen((o) => !o);
        }}
      >
        <img src={hoggieSrc(item.heroHedgehog)} alt="" />
        <span>{item.heroHedgehog}</span>
        <span aria-hidden>▾</span>
      </button>
      {open && (
        <div className="hog-panel">
          <input
            className="hog-search mono"
            aria-label="Search hoggies"
            placeholder={`Search ${hoggieCatalog.length} hoggies…`}
            value={query}
            onChange={(e) => setQuery(e.target.value)}
          />
          <div className="hog-grid">
            {query.trim() === "" && (
              <button
                type="button"
                title="The app default — renders without any network"
                className={
                  active && item.heroHedgehog === defaultSlug
                    ? "hog-cell hog-cell-active"
                    : "hog-cell"
                }
                onClick={() => {
                  onChange({ heroType: "hedgehog", heroHedgehog: defaultSlug });
                  setOpen(false);
                }}
              >
                <img
                  src={hoggieSrc(defaultSlug)}
                  alt=""
                  loading="lazy"
                  decoding="async"
                />
                <span>Default</span>
              </button>
            )}
            {results.map((h) => (
              <button
                key={h.slug}
                type="button"
                title={h.name}
                className={
                  active && item.heroHedgehog === h.slug
                    ? "hog-cell hog-cell-active"
                    : "hog-cell"
                }
                onClick={() => {
                  onChange({ heroType: "hedgehog", heroHedgehog: h.slug });
                  setOpen(false);
                }}
              >
                <img src={h.src} alt="" loading="lazy" decoding="async" />
                <span>{h.name}</span>
              </button>
            ))}
            {results.length === 0 && (
              <p className="hog-none">No hoggies match.</p>
            )}
          </div>
        </div>
      )}
    </div>
  );
}

function ColorPicker({
  item,
  onChange,
}: {
  item: EditableItem;
  onChange: OnChange;
}) {
  const [open, setOpen] = useState(false);
  const selected = BAND_COLORS.find((color) => color.hex === item.heroColor);
  // A hex outside the presets can only come in via Raw JSON — show it as is.
  const label = item.heroColor ? (selected?.name ?? item.heroColor) : "default";
  const pick = (hex: string) => {
    onChange({ heroType: "hedgehog", heroColor: hex });
    setOpen(false);
  };

  return (
    <div className="hog-pick">
      <button
        type="button"
        className="hog-current"
        title="Band color"
        onClick={() => setOpen((o) => !o)}
      >
        <span
          className="swatch"
          style={{ background: item.heroColor || defaultColor(item.kind) }}
          aria-hidden
        />
        <span>{label}</span>
        <span aria-hidden>▾</span>
      </button>
      {open && (
        <div className="hog-panel color-panel">
          <button
            type="button"
            className={
              item.heroColor === ""
                ? "color-cell color-cell-active"
                : "color-cell"
            }
            onClick={() => pick("")}
          >
            <span
              className="swatch"
              style={{ background: defaultColor(item.kind) }}
              aria-hidden
            />
            <span>default</span>
          </button>
          {BAND_COLORS.map((color) => (
            <button
              key={color.hex}
              type="button"
              className={
                item.heroColor === color.hex
                  ? "color-cell color-cell-active"
                  : "color-cell"
              }
              onClick={() => pick(color.hex)}
            >
              <span
                className="swatch"
                style={{ background: color.hex }}
                aria-hidden
              />
              <span>{color.name}</span>
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

function PrimaryAction({
  item,
  stale,
  onChange,
}: {
  item: EditableItem;
  stale: boolean;
  onChange: OnChange;
}) {
  if (item.kind === "required-update") {
    return <span className="st-btn st-btn-solid">Restart to update</span>;
  }
  if (stale) {
    return <span className="st-btn st-btn-solid">Update now</span>;
  }
  if (item.requiresAck) {
    return (
      <input
        className="st-btn st-btn-solid st-btn-edit"
        aria-label="Acknowledge button label"
        placeholder="OK"
        size={Math.max(3, (item.ackLabel || "OK").length + 1)}
        value={item.ackLabel}
        onChange={(e) => onChange({ ackLabel: e.target.value })}
      />
    );
  }
  return (
    <input
      className="st-btn st-btn-edit"
      aria-label="Button label — leave empty for no button"
      title="Leave empty for no button"
      placeholder="+ button"
      size={Math.max(4, (item.ctaLabel || "+ button").length)}
      value={item.ctaLabel}
      onChange={(e) => onChange({ ctaLabel: e.target.value })}
    />
  );
}

function BannerEdit({
  item,
  stale,
  onChange,
}: {
  item: EditableItem;
  stale: boolean;
  onChange: OnChange;
}) {
  return (
    <div className="st-banner">
      <span className="st-banner-icon" aria-hidden>
        📣
      </span>
      <div className="st-banner-text">
        <input
          className="st-edit st-banner-title"
          aria-label="Title"
          placeholder="Announcement title"
          value={item.title}
          onChange={(e) => onChange({ title: e.target.value })}
        />
        <input
          className="st-edit st-banner-sub"
          aria-label="Message — banners show a single line"
          title="Banners show a single line"
          placeholder="One-line message"
          value={item.body}
          onChange={(e) => onChange({ body: e.target.value })}
        />
      </div>
      {stale ? (
        <span className="st-btn st-btn-solid">Update now</span>
      ) : (
        <PrimaryAction item={item} stale={stale} onChange={onChange} />
      )}
      <span className="st-x" aria-hidden>
        ✕
      </span>
    </div>
  );
}

function ModalEdit({
  item,
  stale,
  onChange,
}: {
  item: EditableItem;
  stale: boolean;
  onChange: OnChange;
}) {
  const blocking = item.kind === "required-update" || item.requiresAck;
  return (
    <div className="st-scrim">
      <div className="st-modal">
        {item.heroType !== "none" && <HeroBand item={item} />}
        <div className="st-modal-inner">
          <input
            className="st-edit st-title"
            aria-label="Title"
            placeholder="Announcement title"
            value={item.title}
            onChange={(e) => onChange({ title: e.target.value })}
          />
          <textarea
            className="st-edit st-body-text"
            aria-label="Body — markdown renders in the app"
            title="Markdown renders in the app"
            placeholder="Write the announcement. Markdown works."
            rows={Math.min(10, Math.max(3, item.body.split("\n").length))}
            value={item.body}
            onChange={(e) => onChange({ body: e.target.value })}
          />
          <div className="st-actions">
            {!blocking && <span className="st-btn">Dismiss</span>}
            <PrimaryAction item={item} stale={stale} onChange={onChange} />
          </div>
        </div>
      </div>
    </div>
  );
}

/**
 * The editing surface: the announcement rendered inside a mock desktop app,
 * with the copy edited directly in place. Everything visual is configured
 * from the toolbar above the frame; everything else lives in the props strip.
 */
export function Stage({
  item,
  onChange,
}: {
  item: EditableItem;
  onChange: OnChange;
}) {
  const isAnnouncement = item.kind === "announcement";
  const canToggleState = isAnnouncement && item.minVersion !== "";
  const [viewStale, setViewStale] = useState(false);
  const [previewDark, setPreviewDark] = useState(false);
  useEffect(() => {
    if (!canToggleState) setViewStale(false);
  }, [canToggleState]);
  const stale = !isAnnouncement || (canToggleState && viewStale);
  const isBanner = isAnnouncement && item.style === "banner";

  return (
    <div className="stage">
      <div className="st-toolbar">
        {isAnnouncement && (
          <fieldset className="seg" aria-label="Display style">
            <button
              type="button"
              className={segCls(item.style === "banner")}
              onClick={() => onChange({ style: "banner", requiresAck: false })}
            >
              banner
            </button>
            <button
              type="button"
              className={segCls(item.style === "modal" && !item.requiresAck)}
              onClick={() => onChange({ style: "modal", requiresAck: false })}
            >
              modal
            </button>
            <button
              type="button"
              className={segCls(item.requiresAck)}
              title="No dismiss, no Esc — only the acknowledge button clears it. Updating counts as acknowledging."
              onClick={() => onChange({ style: "modal", requiresAck: true })}
            >
              blocking
            </button>
          </fieldset>
        )}
        {!isBanner && (
          <div className="hero-tools">
            <fieldset className="seg" aria-label="Hero type">
              <button
                type="button"
                className={segCls(item.heroType === "hedgehog")}
                onClick={() => onChange({ heroType: "hedgehog" })}
              >
                hog
              </button>
              <button
                type="button"
                className={segCls(item.heroType === "image")}
                onClick={() => onChange({ heroType: "image" })}
              >
                image
              </button>
              <button
                type="button"
                className={segCls(item.heroType === "none")}
                onClick={() => onChange({ heroType: "none" })}
              >
                none
              </button>
            </fieldset>
            {item.heroType === "hedgehog" && (
              <div className="hero-config">
                <HoggiePicker item={item} onChange={onChange} />
                <ColorPicker item={item} onChange={onChange} />
              </div>
            )}
            {item.heroType === "image" && (
              <input
                className="mono st-img-url"
                aria-label="Hero image URL — https only"
                placeholder="https://…"
                value={item.heroImageUrl}
                onChange={(e) => onChange({ heroImageUrl: e.target.value })}
              />
            )}
          </div>
        )}
        <span className="spacer" />
        {canToggleState && (
          <fieldset className="seg" aria-label="Previewed app version">
            <button
              type="button"
              className={segCls(!viewStale)}
              onClick={() => setViewStale(false)}
            >
              up to date
            </button>
            <button
              type="button"
              className={segCls(viewStale)}
              onClick={() => setViewStale(true)}
            >
              below {item.minVersion}
            </button>
          </fieldset>
        )}
        <fieldset className="seg" aria-label="Preview theme">
          <button
            type="button"
            className={`${segCls(!previewDark)} theme-btn`}
            aria-label="Light preview"
            title="Light preview"
            onClick={() => setPreviewDark(false)}
          >
            <SunIcon />
          </button>
          <button
            type="button"
            className={`${segCls(previewDark)} theme-btn`}
            aria-label="Dark preview"
            title="Dark preview"
            onClick={() => setPreviewDark(true)}
          >
            <MoonIcon />
          </button>
        </fieldset>
      </div>

      <div className={previewDark ? "st-frame st-dark" : "st-frame"}>
        <div className="st-titlebar" aria-hidden>
          <span className="st-dot" />
          <span className="st-dot" />
          <span className="st-dot" />
          <span className="st-tab" />
        </div>
        {isBanner && (
          <BannerEdit item={item} stale={stale} onChange={onChange} />
        )}
        <div className="st-body">
          <div className="st-sidebar" aria-hidden>
            <span />
            <span />
            <span />
            <span />
          </div>
          <div className="st-content" aria-hidden>
            <span />
            <span />
            <span />
            <span />
            <span />
          </div>
          {!isBanner && (
            <ModalEdit item={item} stale={stale} onChange={onChange} />
          )}
        </div>
      </div>
    </div>
  );
}
