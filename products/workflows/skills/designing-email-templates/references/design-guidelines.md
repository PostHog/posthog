# Email design guidelines

These guidelines adapt strong frontend design practice to the email medium — they apply to the Unlayer design as a whole and to the markup fragments inside its text blocks. The goal is a template that looks deliberately designed for the brand — not a generic notification.

## Commit to a direction first

Before writing markup, decide:

- **Purpose and audience** — transactional receipt, product announcement, win-back campaign, and onboarding emails each warrant different energy.
- **Tone** — pick one and execute it precisely: brutally minimal, editorial/magazine, luxury/refined, playful, industrial/utilitarian. Intentionality beats intensity.
- **Brand** — pull real colors, voice, and logo from the sender's product or site. If given a URL, mine it for the palette and typographic feel.
- **The memorable thing** — one element the reader will remember: a bold header treatment, a striking stat, an unusual color block. One, not five.

## Typography

- Build hierarchy with **size, weight, and color contrast**, not font variety: one display treatment for the headline (large, tight line-height, heavy weight), one comfortable body style (15–17px, 1.5–1.6 line-height).
- Web-safe stacks can still have character: `Georgia, 'Times New Roman', serif` reads editorial; `'Trebuchet MS', Tahoma, sans-serif` reads friendly; `'Courier New', monospace` reads technical. Choose to match the tone instead of defaulting to Arial everywhere.
- Custom fonts via `<link>`/`@font-face` render in Apple Mail and partially elsewhere — use them as enhancement with a fallback stack that still fits the design.
- Constrain line length (~35em); let headlines breathe with padding above and below.

## Color

- Commit to a small palette: one dominant color, one sharp accent for the CTA, neutrals for text. Evenly-distributed timid palettes read as template-default; dominant-plus-accent reads as designed.
- Use consistent hex values everywhere (no CSS variables in email — repeat the literal values; keep a comment block at the top of the document listing the palette so edits stay consistent).
- Check contrast: body text ≥ 4.5:1 against its background. Test the design holds on both white and dark backgrounds — many clients force dark mode and invert naive black-on-white.

## Layout and space

- Asymmetry and overlap are mostly unavailable in table layout — get visual interest from **generous, deliberate whitespace**, full-bleed color sections, and strong alignment instead.
- Vary section rhythm: a full-width color band for the header, padded white content sections, a tight dark footer. Uniform 20px-padding-everywhere is what makes emails look auto-generated.
- One column. Side-by-side cells should be rare, content-justified, and must degrade acceptably when stacked.

## Visual details that survive email clients

- **Bulletproof CTA buttons**: a padded `<td>` with `bgcolor`, border-radius, and an inline-styled `<a>` — not an image, not a CSS-only button.
- Solid `bgcolor` sections, border accents (a 4px top border in the accent color is cheap and distinctive), and spacer rows are the reliable atmosphere tools. Gradients, background images, and shadows are enhancement-only — the design must work without them.
- A real text preheader (hidden with inline styles) controls the inbox preview line — write it like ad copy, don't let the client scrape your header nav.

## What reads as machine-generated (avoid)

Centered white card on gray, purple gradient header, Arial everywhere at uniform sizes, three equal feature columns with stock icons, evenly-spread pastel palette, "Hi {name}," as the only personalization. If the draft resembles that, the direction wasn't committed to — restart from the tone decision, don't polish it.

## Quality pass before saving

1. Read the design top to bottom: every text-block element styled inline, palette values consistent, alt text on images.
2. Squint test on the rendered preview: clear hierarchy — eye lands on headline → key message → CTA.
3. Confirm Liquid variables have `| default:` fallbacks so no reader sees a blank.
4. Confirm the plain-text version carries the full message, not a stub.
