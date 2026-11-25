//! Laying out blocks: each block's text is shaped once into wrapped lines
//! and kept until the block, the width or the theme changes. Positions,
//! hit-testing, carets and selection rectangles are worked out from those
//! lines here; `element` only paints them.
use super::model::{Block, Kind, Style};
use gpui_kit::*;
use std::ops::Range;

pub const GUTTER: f32 = 48.;
pub const INDENT: f32 = 24.;
pub const MARKER: f32 = 24.;
pub const MARKER_GAP: f32 = 2.;
pub const QUOTE_INSET: f32 = 17.;

pub const SANS: &str = ".SystemUIFont";
pub const MONO: &str = "Menlo";

/// Colors resolved from the user's theme for one frame.
#[derive(Clone, Copy, PartialEq)]
pub struct Colors {
    pub ink: Hsla,
    pub secondary: Hsla,
    pub tertiary: Hsla,
    pub canvas: Hsla,
    pub inset: Hsla,
    pub rule: Hsla,
    pub accent: Hsla,
    pub danger: Hsla,
    pub accent_fg: Hsla,
    pub dark: bool,
    /// A cheap fingerprint of the palette, part of every layout's key.
    pub key: u64,
}

impl Colors {
    pub fn current() -> Self {
        use crate::sdk::ui::theme;
        let c = |i: usize| -> Hsla { rgb(theme::get(i)).into() };
        let mut key = 0u64;
        for i in 0..14 {
            key = key
                .wrapping_mul(0x100_0000_01b3)
                .wrapping_add(theme::get(i) as u64);
        }
        Self {
            ink: c(0),
            secondary: c(1),
            tertiary: c(2),
            canvas: c(3),
            inset: c(4),
            rule: c(5),
            danger: c(8),
            accent: c(10),
            accent_fg: c(13),
            dark: theme::is_dark(),
            key,
        }
    }
    /// The ink at an opacity: hovers, muted text, hairlines.
    pub fn ink_alpha(&self, a: f32) -> Hsla {
        let mut c = self.ink;
        c.a = a;
        c
    }
    pub fn selection(&self) -> Hsla {
        let mut c = self.accent;
        c.a = if self.dark { 0.42 } else { 0.26 };
        c
    }
    pub fn block_selection(&self) -> Hsla {
        let mut c = self.accent;
        c.a = if self.dark { 0.22 } else { 0.13 };
        c
    }
    pub fn code_bg(&self) -> Hsla {
        self.ink_alpha(if self.dark { 0.09 } else { 0.055 })
    }
    pub fn inline_code_bg(&self) -> Hsla {
        self.ink_alpha(if self.dark { 0.14 } else { 0.08 })
    }
    pub fn hover(&self) -> Hsla {
        self.ink_alpha(if self.dark { 0.1 } else { 0.06 })
    }
}

/// Type and spacing of one kind of block (Notion's rhythm at a 16 px body).
#[derive(Clone, Copy)]
pub struct Metrics {
    pub font_size: f32,
    pub line_height: f32,
    pub weight: FontWeight,
    pub mono: bool,
    pub pad_top: f32,
    pub pad_bottom: f32,
    pub margin_top: f32,
    pub margin_bottom: f32,
}

pub fn metrics(kind: Kind) -> Metrics {
    let body = Metrics {
        font_size: 16.,
        line_height: 24.,
        weight: FontWeight::NORMAL,
        mono: false,
        pad_top: 3.,
        pad_bottom: 3.,
        margin_top: 1.,
        margin_bottom: 1.,
    };
    match kind {
        Kind::H1 => Metrics {
            font_size: 30.,
            line_height: 39.,
            weight: FontWeight::SEMIBOLD,
            margin_top: 30.,
            margin_bottom: 4.,
            ..body
        },
        Kind::H2 => Metrics {
            font_size: 24.,
            line_height: 31.,
            weight: FontWeight::SEMIBOLD,
            margin_top: 20.,
            margin_bottom: 1.,
            ..body
        },
        Kind::H3 => Metrics {
            font_size: 20.,
            line_height: 26.,
            weight: FontWeight::SEMIBOLD,
            margin_top: 14.,
            margin_bottom: 1.,
            ..body
        },
        Kind::Quote => Metrics {
            font_size: 18.,
            line_height: 27.,
            margin_top: 4.,
            margin_bottom: 4.,
            ..body
        },
        Kind::Code => Metrics {
            font_size: 13.5,
            line_height: 21.,
            mono: true,
            pad_top: 16.,
            pad_bottom: 16.,
            margin_top: 6.,
            margin_bottom: 6.,
            ..body
        },
        Kind::Divider => Metrics {
            line_height: 13.,
            pad_top: 4.,
            pad_bottom: 4.,
            ..body
        },
        _ => body,
    }
}

pub const CODE_PAD_X: f32 = 18.;

/// Where a block's text starts, from the block's left edge (after indent).
pub fn text_inset(kind: Kind, marker: f32) -> f32 {
    match kind {
        Kind::Bullet | Kind::Numbered | Kind::Todo => marker + MARKER_GAP,
        Kind::Quote => QUOTE_INSET,
        Kind::Code => CODE_PAD_X,
        _ => 2.,
    }
}

/// One row of text as painted: part of a hard line between wrap points.
#[derive(Clone, Debug)]
pub struct VisualLine {
    /// Index into `BlockLayout::lines`.
    pub line: usize,
    /// Offsets in the block's text.
    pub start: usize,
    pub end: usize,
    /// Where the hard line starts in the block's text.
    pub base: usize,
    /// x of `start` in the unwrapped line.
    pub x0: Pixels,
    /// Top, from the text's origin.
    pub y: Pixels,
    /// Whether another row of the same hard line follows (a soft wrap).
    pub wraps: bool,
}

/// What a block's layout was made from: it is reused while this matches.
#[derive(Clone, PartialEq)]
pub struct LayoutKey {
    pub rev: u64,
    pub width: Pixels,
    pub colors: u64,
    pub marker: Pixels,
    pub marked: Option<Range<usize>>,
}

pub struct BlockLayout {
    pub key: LayoutKey,
    pub kind: Kind,
    pub lines: Vec<WrappedLine>,
    pub visual: Vec<VisualLine>,
    pub metrics: Metrics,
    /// The text's origin, from the block's top-left (after indent).
    pub text_x: Pixels,
    pub text_y: Pixels,
    pub line_height: Pixels,
    /// Height without margins.
    pub height: Pixels,
}

pub fn font(m: &Metrics) -> Font {
    let mut f = gpui_kit::font(if m.mono { MONO } else { SANS });
    f.weight = m.weight;
    f
}

/// The styled runs for a block's text: marks, IME composition and the
/// done state of a to-do.
pub fn runs(
    block: &Block,
    m: &Metrics,
    colors: &Colors,
    marked: Option<&Range<usize>>,
) -> Vec<TextRun> {
    let base_font = font(m);
    let len = block.text.len();
    let mut cuts: Vec<usize> = vec![0, len];
    for mark in &block.marks {
        cuts.push(mark.start.min(len));
        cuts.push(mark.end.min(len));
    }
    if let Some(r) = marked {
        cuts.push(r.start.min(len));
        cuts.push(r.end.min(len));
    }
    cuts.sort_unstable();
    cuts.dedup();
    let done = block.kind == Kind::Todo && block.checked;
    let ink = if done {
        colors.ink_alpha(0.42)
    } else {
        colors.ink
    };
    let mut out = Vec::with_capacity(cuts.len());
    for w in cuts.windows(2) {
        let (a, b) = (w[0], w[1]);
        if a == b {
            continue;
        }
        let mut f = base_font.clone();
        let mut color = ink;
        let mut background = None;
        let mut underline = None;
        let mut strike = done.then_some(StrikethroughStyle {
            thickness: px(1.),
            color: Some(ink),
        });
        if block.kind != Kind::Code {
            for mark in block.marks.iter().filter(|m| m.start <= a && m.end >= b) {
                match &mark.style {
                    Style::Bold => {
                        f.weight = if m.weight == FontWeight::NORMAL {
                            FontWeight::SEMIBOLD
                        } else {
                            FontWeight::BOLD
                        }
                    }
                    Style::Italic => f.style = FontStyle::Italic,
                    Style::Code => {
                        f.family = MONO.into();
                        color = if done {
                            colors.ink_alpha(0.42)
                        } else {
                            colors.danger
                        };
                        background = Some(colors.inline_code_bg());
                    }
                    Style::Strike => {
                        strike = Some(StrikethroughStyle {
                            thickness: px(1.),
                            color: Some(color),
                        })
                    }
                    Style::Link(_) => {
                        underline = Some(UnderlineStyle {
                            thickness: px(1.),
                            color: Some(colors.ink_alpha(0.4)),
                            wavy: false,
                        })
                    }
                }
            }
        }
        if marked.is_some_and(|r| r.start <= a && r.end >= b) {
            underline = Some(UnderlineStyle {
                thickness: px(1.5),
                color: Some(colors.ink_alpha(0.8)),
                wavy: false,
            });
        }
        out.push(TextRun {
            len: b - a,
            font: f,
            color,
            background_color: background,
            underline,
            strikethrough: strike,
        });
    }
    out
}

/// Shapes a block's text at a width.
pub fn layout_block(
    block: &Block,
    key: LayoutKey,
    colors: &Colors,
    window: &mut Window,
) -> BlockLayout {
    let m = metrics(block.kind);
    let text_x = px(text_inset(block.kind, f32::from(key.marker)));
    let right_pad = if block.kind == Kind::Code {
        px(CODE_PAD_X)
    } else {
        px(0.)
    };
    let wrap = (key.width - text_x - right_pad).max(px(40.));
    let line_height = px(m.line_height);
    let (lines, visual) = if block.kind == Kind::Divider {
        (Vec::new(), Vec::new())
    } else {
        let runs = runs(block, &m, colors, key.marked.as_ref());
        let lines: Vec<WrappedLine> = window
            .text_system()
            .shape_text(
                SharedString::from(block.text.clone()),
                px(m.font_size),
                &runs,
                Some(wrap),
                None,
            )
            .map(|l| l.into_iter().collect())
            .unwrap_or_default();
        let visual = visual_lines(&lines, line_height);
        (lines, visual)
    };
    let rows = visual.len().max(1);
    let content = if block.kind == Kind::Divider {
        line_height
    } else {
        line_height * rows as f32
    };
    BlockLayout {
        key,
        kind: block.kind,
        lines,
        visual,
        metrics: m,
        text_x,
        text_y: px(m.pad_top),
        line_height,
        height: px(m.pad_top) + content + px(m.pad_bottom),
    }
}

fn visual_lines(lines: &[WrappedLine], line_height: Pixels) -> Vec<VisualLine> {
    let mut out = Vec::new();
    let mut base = 0;
    let mut row = 0;
    for (i, line) in lines.iter().enumerate() {
        let layout = &line.unwrapped_layout;
        let mut starts = vec![0usize];
        for b in line.wrap_boundaries() {
            if let Some(g) = layout
                .runs
                .get(b.run_ix)
                .and_then(|r| r.glyphs.get(b.glyph_ix))
            {
                starts.push(g.index);
            }
        }
        let len = line.len();
        for (k, s) in starts.iter().enumerate() {
            let e = starts.get(k + 1).copied().unwrap_or(len);
            out.push(VisualLine {
                line: i,
                start: base + s,
                end: base + e,
                base,
                x0: layout.x_for_index(*s),
                y: line_height * row as f32,
                wraps: k + 1 < starts.len(),
            });
            row += 1;
        }
        base += len + 1;
    }
    if out.is_empty() {
        out.push(VisualLine {
            line: 0,
            start: 0,
            end: 0,
            base: 0,
            x0: px(0.),
            y: px(0.),
            wraps: false,
        });
    }
    out
}

impl BlockLayout {
    /// The row a caret at `offset` is drawn on. At a soft wrap the caret
    /// belongs to the next row unless `upstream`.
    pub fn row_of(&self, offset: usize, upstream: bool) -> usize {
        for (i, v) in self.visual.iter().enumerate() {
            let last_of_line = !v.wraps;
            if (offset < v.end || (offset == v.end && (last_of_line || upstream)))
                && offset >= v.start
            {
                return i;
            }
        }
        self.visual.len().saturating_sub(1)
    }

    /// x of an offset within its row, from the text origin.
    pub fn x_of(&self, row: usize, offset: usize) -> Pixels {
        let Some(v) = self.visual.get(row) else {
            return px(0.);
        };
        let Some(line) = self.lines.get(v.line) else {
            return px(0.);
        };
        let local = offset.clamp(v.start, v.end) - v.base;
        line.unwrapped_layout.x_for_index(local) - v.x0
    }

    /// The caret's position (top of its row) from the text origin.
    pub fn caret(&self, offset: usize, upstream: bool) -> Point<Pixels> {
        let row = self.row_of(offset, upstream);
        let y = self.visual.get(row).map(|v| v.y).unwrap_or_default();
        point(self.x_of(row, offset), y)
    }

    /// The offset closest to x on a row. The second value is true when the
    /// offset sits at a soft wrap at the end of the row (draw it upstream).
    pub fn offset_at(&self, row: usize, x: Pixels) -> (usize, bool) {
        let Some(v) = self.visual.get(row) else {
            return (0, false);
        };
        let Some(line) = self.lines.get(v.line) else {
            return (v.start, false);
        };
        let layout = &line.unwrapped_layout;
        let local = closest_index(layout, x.max(px(0.)) + v.x0);
        let mut offset = (v.base + local).clamp(v.start, v.end);
        let mut upstream = false;
        if v.wraps && offset >= v.end {
            // Past the end of a wrapped row: before its trailing space, or
            // at the wrap itself, drawn on this row.
            offset = v.end;
            upstream = true;
        }
        (offset, upstream)
    }

    /// The row at y (from the text origin), clamped.
    pub fn row_at(&self, y: Pixels) -> usize {
        if y < px(0.) {
            return 0;
        }
        let row = (y / self.line_height).floor() as usize;
        row.min(self.visual.len().saturating_sub(1))
    }

    /// Rectangles covering `range`, from the text origin. A selection that
    /// continues past a row's end extends a little past its text, as macOS
    /// shows the newline.
    pub fn range_rects(&self, range: Range<usize>, continues: bool) -> Vec<Bounds<Pixels>> {
        let mut out = Vec::new();
        for (i, v) in self.visual.iter().enumerate() {
            if range.end < v.start || range.start > v.end {
                continue;
            }
            let last_row = i + 1 == self.visual.len();
            let s = range.start.max(v.start);
            let e = range.end.min(v.end);
            let x0 = self.x_of(i, s);
            let mut x1 = self.x_of(i, e);
            let past_end =
                range.end > v.end || (last_row && continues) || (!v.wraps && range.end > v.end);
            if past_end {
                x1 += px(5.);
            }
            if x1 <= x0 && !past_end {
                continue;
            }
            out.push(Bounds::from_corners(
                point(x0, v.y),
                point(x1.max(x0 + px(1.)), v.y + self.line_height),
            ));
        }
        out
    }

    /// Height of a caret for this block's type.
    pub fn caret_height(&self) -> Pixels {
        px((self.metrics.font_size * 1.25).min(self.metrics.line_height))
    }
}

/// Shapes a single line of chrome text (placeholders, numbers).
pub fn shape_line(
    text: &str,
    size: f32,
    color: Hsla,
    weight: FontWeight,
    window: &mut Window,
) -> ShapedLine {
    let mut f = gpui_kit::font(SANS);
    f.weight = weight;
    let run = TextRun {
        len: text.len(),
        font: f,
        color,
        background_color: None,
        underline: None,
        strikethrough: None,
    };
    window
        .text_system()
        .shape_line(SharedString::from(text.to_owned()), px(size), &[run], None)
}

/// The character boundary nearest x. GPUI's `closest_index_for_x` answers
/// the line's end for anything past the last glyph's start, which put a
/// click on the left half of a line's last character after it.
fn closest_index(layout: &LineLayout, x: Pixels) -> usize {
    let mut prev_index = 0;
    let mut prev_x = px(0.);
    for run in &layout.runs {
        for glyph in &run.glyphs {
            if glyph.position.x >= x {
                return if glyph.position.x - x < x - prev_x {
                    glyph.index
                } else {
                    prev_index
                };
            }
            prev_index = glyph.index;
            prev_x = glyph.position.x;
        }
    }
    if layout.width - x < x - prev_x {
        layout.len
    } else {
        prev_index
    }
}
