use futures::Stream as _;
#[cfg(not(target_family = "wasm"))]
use std::time::Instant;
use std::{
    ops::{Range, RangeInclusive},
    pin::Pin,
    sync::{Arc, Mutex, OnceLock},
    task::Poll,
    time::Duration,
};
#[cfg(target_family = "wasm")]
use web_time::Instant;

use gpui::{
    App, AppContext as _, Bounds, Context, EntityId, FocusHandle, IntoElement, KeyBinding,
    ListState, ParentElement as _, Pixels, Point, Render, SharedString, Styled as _, Task, Window,
    prelude::FluentBuilder as _, px,
};

use crate::{
    AutoScroll, ElementExt, TextSelection,
    async_util::{Receiver, Sender, unbounded},
    input::{self, SelectAll},
    text::{
        CodeBlockActionsFn, CodeBlockHighlighterFn, LinkClickHandlerFn, MarkdownExtensions,
        RangeHighlight, RangeHighlightError, RenderedText, TableActionsFn, TextViewStyle,
        document::ParsedDocument,
        format,
        node::{self, NodeContext},
        range_highlight::{
            LeafRemap, PendingReveal, RangeHighlightFrame, RenderedIndex, RevealRequest,
        },
        selection_adapter::TextViewSelectionAdapter,
        stream_fade::{StreamFadeTracker, TextViewMotion},
    },
    touch_selection::caret_line_box,
    v_flex,
};

const CONTEXT: &'static str = "TextView";
// Keep coalescing bounded so sustained streams still render intermediate updates.
const MAX_COALESCED_UPDATES_PER_PARSE: usize = 64;
// Preserve exact first-layout height for small documents while bounding the
// amount of source parsed synchronously on the UI thread.
const MAX_SYNC_FULL_REPLACE_BYTES: usize = 4 * 1024;
// Repaint a streamed fade at about 30 fps, not at the display refresh rate.
const STREAM_FADE_TICK: Duration = Duration::from_millis(33);

pub(crate) fn init(cx: &mut App) {
    cx.bind_keys(vec![
        #[cfg(target_os = "macos")]
        KeyBinding::new("cmd-c", input::Copy, Some(CONTEXT)),
        #[cfg(not(target_os = "macos"))]
        KeyBinding::new("ctrl-c", input::Copy, Some(CONTEXT)),
        #[cfg(target_os = "macos")]
        KeyBinding::new("cmd-a", input::SelectAll, Some(CONTEXT)),
        #[cfg(not(target_os = "macos"))]
        KeyBinding::new("ctrl-a", input::SelectAll, Some(CONTEXT)),
    ]);
}

/// The content format of the text view.
#[derive(Clone, Copy, PartialEq, Eq)]
pub(super) enum TextViewFormat {
    /// Markdown view
    Markdown,
    /// HTML view
    Html,
}

/// The format of the text returned by
/// [`TextViewState::selected_text`], which is also what copy writes to the
/// clipboard.
#[derive(Debug, Clone, Copy, Default, PartialEq, Eq)]
pub enum SelectionFormat {
    /// The rendered text, without any markup.
    #[default]
    Plain,
    /// The source of the selection.
    ///
    /// Select-all returns the original source verbatim, a partial selection is
    /// reconstructed as Markdown from the parsed nodes (e.g. selecting inside
    /// a `**bold**` run yields `**bold**`).
    Source,
    /// The rendered text while the selection stays within one style, the
    /// source as soon as it takes in several.
    ///
    /// A style is everything the source would spell out around the selected
    /// text: the marks of an inline run (emphasis, code, a link's URL) and the
    /// block it sits in (a heading's `#`, a list marker, a code fence). So
    /// selecting inside a `**bold**` run, a link or a code block yields the
    /// text alone, also when the selection reaches exactly up to the run's
    /// boundaries, while a selection across that boundary, into a second
    /// block, or over an inline object copies like [`Self::Source`]. Two blocks
    /// count as two styles even when their marks match, since the source of
    /// either spells out where one ends. Select-all copies the source verbatim.
    SourceAcrossStyles,
}

/// One text element's laid-out vertical extent, reported by `Inline` during
/// prepaint so `TextView` can snap its `max_lines` clip to a whole-line
/// boundary.
#[derive(Clone, Copy)]
pub(super) struct LineSpan {
    pub(super) top: Pixels,
    pub(super) bottom: Pixels,
    pub(super) line_height: Pixels,
}

/// The state of a TextView.
pub struct TextViewState {
    entity_id: EntityId,
    pub(super) focus_handle: FocusHandle,
    pub(super) list_state: ListState,

    /// The bounds of the text view
    bounds: Bounds<Pixels>,

    pub(super) selectable: bool,
    pub(super) selection_format: SelectionFormat,
    pub(super) scrollable: bool,
    pub(super) max_lines: Option<usize>,
    /// Line spans reported by `Inline` during prepaint (collected only while
    /// [`Self::max_lines`] is set); cleared by `TextView` at each frame start.
    pub(super) line_spans: Arc<Mutex<Vec<LineSpan>>>,
    /// Whether the last painted frame clipped content due to `max_lines`.
    pub(super) clamped: bool,
    pub(super) text_view_style: Arc<TextViewStyle>,
    pub(super) code_block_actions: Option<std::sync::Arc<CodeBlockActionsFn>>,
    pub(super) code_block_highlighter: Option<std::sync::Arc<CodeBlockHighlighterFn>>,
    pub(super) table_actions: Option<std::sync::Arc<TableActionsFn>>,
    pub(super) image_source: Option<std::sync::Arc<super::text_view::ImageSourceFn>>,
    pub(super) link_click_handler: Option<std::sync::Arc<LinkClickHandlerFn>>,
    pub(super) markdown_extensions: Arc<MarkdownExtensions>,

    pub(super) is_selecting: bool,
    /// Logical ranges retained across compatible resource or presentation reflow.
    pub(super) preserve_inline_selection: bool,
    multi_click_selection: Option<TextViewMultiClickSelection>,
    selected_text_override: Option<String>,
    select_all: bool,
    pub(super) auto_scroll: AutoScroll,
    pub(super) selection_adapter: TextViewSelectionAdapter,

    pub(super) parsed_content: ParsedContent,
    pub(super) stream_fade: StreamFadeTracker,
    fade_tick: Option<Task<()>>,
    /// Content format (markdown / html), used for bounded synchronous parsing
    /// of small full-replace updates.
    format: TextViewFormat,
    text: String,
    /// The text a `TextView` element last handed over, to recognize the same
    /// string next frame without comparing its bytes.
    element_text: Option<SharedString>,
    revision: usize,
    /// The revision of the update `parsed_content` was committed from.
    committed_revision: usize,
    /// The revision of the last update that replaced the text rather than
    /// appending to it.
    full_update_revision: usize,
    /// The rendered text of `parsed_content`, built when first read.
    rendered_index: Arc<OnceLock<RenderedIndex>>,
    range_highlights: Option<Arc<RangeHighlightFrame>>,
    pub(super) pending_reveal: Option<PendingReveal>,
    pub(super) selection_revision: usize,
    compatible_layout_update: bool,
    layout_text_style: Option<(gpui::TextStyle, Pixels)>,
    parsed_error: Option<SharedString>,
    tx: Sender<UpdateOptions>,
    _parse_task: Task<()>,
    _receive_task: Task<()>,
}

impl TextViewState {
    /// Create a Markdown TextViewState.
    pub fn markdown(text: &str, cx: &mut Context<Self>) -> Self {
        Self::new(TextViewFormat::Markdown, text, cx)
    }

    /// Create a HTML TextViewState.
    pub fn html(text: &str, cx: &mut Context<Self>) -> Self {
        Self::new(TextViewFormat::Html, text, cx)
    }

    /// Create a new TextViewState.
    fn new(format: TextViewFormat, text: &str, cx: &mut Context<Self>) -> Self {
        let focus_handle = cx.focus_handle();
        let selection_adapter = TextViewSelectionAdapter::new(cx.entity().downgrade(), cx);

        let (tx, rx) = unbounded::<UpdateOptions>();
        let (tx_result, rx_result) = unbounded::<ParsedUpdate>();
        let _receive_task = cx.spawn({
            async move |weak_self, cx| {
                while let Ok(parsed_update) = rx_result.recv().await {
                    // A result that commits nothing — the background parser
                    // acknowledging a synchronous parse — leaves the state
                    // alone: updating it would tell GPUI Fast's retained
                    // views that read it that it changed.
                    let Ok(commits) =
                        weak_self.read_with(cx, |state, _| state.commits(&parsed_update))
                    else {
                        break;
                    };
                    if !commits {
                        continue;
                    }
                    _ = weak_self.update(cx, |state, cx| {
                        state.commit_parsed_update(parsed_update, cx);
                    });
                }
            }
        });

        let _parse_task = cx.background_spawn(UpdateFuture::new(format, rx, tx_result));

        let mut this = Self {
            entity_id: cx.entity_id(),
            focus_handle,
            bounds: Bounds::default(),
            multi_click_selection: None,
            selected_text_override: None,
            select_all: false,
            selectable: false,
            selection_format: SelectionFormat::default(),
            scrollable: false,
            max_lines: None,
            line_spans: Arc::default(),
            clamped: false,
            // Measure all blocks (not just visible ones) so the scrollbar
            // thumb size stays stable. Without this, off-screen blocks count
            // as zero height until scrolled into view, which makes the
            // scrollbar jitter as more blocks get measured during scrolling.
            list_state: ListState::new(0, gpui::ListAlignment::Top, px(1000.)).measure_all(),
            text_view_style: Arc::default(),
            code_block_actions: None,
            code_block_highlighter: None,
            table_actions: None,
            link_click_handler: None,
            image_source: None,
            markdown_extensions: Arc::default(),
            is_selecting: false,
            preserve_inline_selection: false,
            auto_scroll: AutoScroll::default(),
            selection_adapter,
            parsed_content: Default::default(),
            stream_fade: StreamFadeTracker::default(),
            fade_tick: None,
            format,
            parsed_error: None,
            text: text.to_string(),
            element_text: None,
            revision: 0,
            committed_revision: 0,
            full_update_revision: 0,
            rendered_index: Arc::default(),
            range_highlights: None,
            pending_reveal: None,
            selection_revision: 0,
            compatible_layout_update: false,
            layout_text_style: None,
            tx,
            _parse_task,
            _receive_task,
        };
        this.increment_update(&text, false, cx);
        this
    }

    /// Get the text content.
    pub(crate) fn source(&self) -> SharedString {
        self.parsed_content.document.source.clone()
    }

    /// Set whether the text is selectable, default false.
    pub fn selectable(mut self, selectable: bool) -> Self {
        self.selectable = selectable;
        self
    }

    /// Set whether the text is selectable, default false.
    pub fn set_selectable(&mut self, selectable: bool, cx: &mut Context<Self>) {
        self.selectable = selectable;
        cx.notify();
    }

    /// Set the [`SelectionFormat`], default is [`SelectionFormat::Plain`].
    pub fn selection_format(mut self, selection_format: SelectionFormat) -> Self {
        self.selection_format = selection_format;
        self
    }

    /// Set the [`SelectionFormat`], default is [`SelectionFormat::Plain`].
    pub fn set_selection_format(
        &mut self,
        selection_format: SelectionFormat,
        cx: &mut Context<Self>,
    ) {
        self.selection_format = selection_format;
        cx.notify();
    }

    /// Set whether the text view scrolls internally, default false.
    pub fn scrollable(mut self, scrollable: bool) -> Self {
        self.scrollable = scrollable;
        self
    }

    /// Set whether the text view scrolls internally, default false.
    pub fn set_scrollable(&mut self, scrollable: bool, cx: &mut Context<Self>) {
        if !scrollable {
            self.reset_selection_and_adapter(cx);
        }
        self.scrollable = scrollable;
        cx.notify();
    }

    /// Whether the last painted frame clipped content because of
    /// [`TextView::max_lines`](crate::text::TextView::max_lines).
    pub fn is_clamped(&self) -> bool {
        self.clamped
    }

    /// Set the text content.
    ///
    /// Markdown that extends the current non-empty text is appended like
    /// [`Self::push_str`], keeping the selection; any other text replaces it.
    /// With a streamed fade-in enabled, extended text fades in; a replacement
    /// shows at once.
    pub fn set_text(&mut self, text: &str, cx: &mut Context<Self>) {
        if self.text.as_str() == text {
            return;
        }
        // HTML blocks carry no spans, so an append would parse the delta as a
        // standalone document. After a failed parse the background parser's
        // document lacks that text, so only a full parse resynchronizes it.
        if self.format == TextViewFormat::Markdown
            && self.parsed_error.is_none()
            && !self.text.is_empty()
            && let Some(delta) = text.strip_prefix(self.text.as_str())
        {
            self.push_str(delta, cx);
            return;
        }
        self.stream_fade.note_replace();

        self.text.clear();
        self.text.push_str(text);
        self.parsed_error = None;
        self.increment_update(text, false, cx);
    }

    /// [`Self::set_text`] for the text a `TextView` element hands over every
    /// frame: the string it handed over last time (the same allocation, not
    /// merely equal bytes) is recognized without a comparison, as long as the
    /// state still holds a text of its length.
    pub(super) fn set_element_text(&mut self, text: &SharedString, cx: &mut Context<Self>) {
        let same_string = self.element_text.as_ref().is_some_and(|current| {
            current.as_ptr() == text.as_ptr() && current.len() == text.len()
        });
        if same_string && self.text.len() == text.len() {
            return;
        }
        self.element_text = Some(text.clone());
        self.set_text(text, cx);
    }

    /// Append partial text content to the existing text.
    pub fn push_str(&mut self, new_text: &str, cx: &mut Context<Self>) {
        if new_text.is_empty() {
            return;
        }
        self.stream_fade.note_extend(self.text.len());
        self.text.push_str(new_text);
        self.increment_update(new_text, true, cx);
    }

    /// Set the motion policy; see [`TextViewMotion`].
    pub fn motion(mut self, motion: TextViewMotion) -> Self {
        self.set_motion(motion);
        self
    }

    /// Set the motion policy; see [`TextViewMotion`].
    pub fn set_motion(&mut self, motion: TextViewMotion) {
        self.stream_fade.set_motion(motion);
    }

    pub(crate) fn set_markdown_extensions(
        &mut self,
        markdown_extensions: Arc<MarkdownExtensions>,
        cx: &mut Context<Self>,
    ) {
        if self.markdown_extensions.revision() == markdown_extensions.revision() {
            return;
        }

        let parser_configuration_changed = !self
            .markdown_extensions
            .has_same_parser_configuration(&markdown_extensions);
        self.markdown_extensions = markdown_extensions;
        if parser_configuration_changed && self.format == TextViewFormat::Markdown {
            let text = self.text.clone();
            self.increment_update(&text, false, cx);
        }
    }

    /// Return the selected text, in the view's [`SelectionFormat`].
    pub fn selected_text(&self) -> String {
        self.selected_text_in(None)
    }

    /// Return the original Markdown source byte range corresponding to the
    /// rendered selection.
    ///
    /// The range addresses the source passed to this Markdown TextView. It is
    /// derived from parser positions retained by the rendered inline nodes, so
    /// identical rendered text maps to the occurrence that was actually
    /// selected. The result is one contiguous source range, so it includes any
    /// Markdown delimiters between the selected rendered endpoints. HTML views
    /// and selections without an exact source mapping return `None`. Select-all
    /// in a Markdown view returns the full source range.
    pub fn selected_source_range(&self) -> Option<Range<usize>> {
        if self.format != TextViewFormat::Markdown {
            return None;
        }
        if self.select_all {
            return Some(0..self.source().len());
        }
        self.parsed_content.document.selected_source_range()
    }

    /// The format to copy in, which is [`SelectionFormat::Plain`] whenever the
    /// requested one cannot be produced.
    ///
    /// Only a Markdown view can return source. Reconstructing HTML would mean
    /// spelling every attribute back out — a mark's color, an image's
    /// dimensions, a cell's alignment — with a new way to lose one at each
    /// step, and html5ever records no source offsets to fall back on (it
    /// reports only line numbers), so there is no original text to copy from
    /// either.
    fn effective_format(&self) -> SelectionFormat {
        match self.format {
            TextViewFormat::Markdown => self.selection_format,
            TextViewFormat::Html => SelectionFormat::Plain,
        }
    }

    /// A pending full replacement leaves the previous document on screen, but
    /// that document must no longer supply clipboard content.
    pub(super) fn has_current_copy_document(&self) -> bool {
        self.committed_revision >= self.full_update_revision
    }

    /// Return the selected text, with `blocks` bounding which top-level blocks
    /// the selection covers.
    ///
    /// The range comes from the selection endpoints, which know their block
    /// even after it scrolls out of view; see
    /// [`ParsedDocument::selected_text`](crate::text::document::ParsedDocument).
    pub(super) fn selected_text_in(&self, blocks: Option<RangeInclusive<usize>>) -> String {
        let format = self.effective_format();

        if self.select_all {
            if format != SelectionFormat::Plain {
                return self.source().to_string();
            }

            return self.parsed_content.document.text();
        }

        // A multi-click stores the plain text it selected, which is a shortcut
        // past the block walk. Source mode cannot take it: the word it stored
        // has lost its markup. The click also set the inline selection it came
        // from, so the walk reconstructs the same range with the markup intact.
        if format == SelectionFormat::Plain
            && let Some(text) = &self.selected_text_override
        {
            return text.clone();
        }

        self.parsed_content.document.selected_text(format, blocks)
    }

    /// Force a full re-measure of the block list after the document has been
    /// replaced.
    ///
    /// `Document::render_root` only calls `ListState::reset` when the block
    /// *count* changes, and the full-measure pass enabled by `measure_all` is
    /// a one-shot latch that only `reset`, `remeasure_items`, or a width
    /// change re-arms. Replacing a document with one that happens to have the
    /// same number of blocks therefore leaves every cached height belonging to
    /// the *previous* document. The list summary height stays wrong, and since
    /// the wheel clamps against that summary, the blocks past the false bottom
    /// can never scroll into view to be re-measured -- the clamp seals itself.
    ///
    /// `remeasure_items` re-arms the latch and marks the items unmeasured
    /// while keeping their old sizes as hints, so the scrollbar does not
    /// collapse in the frame before the next layout measures the real heights.
    fn invalidate_measured_heights(&self) {
        let count = self.list_state.item_count();
        if count > 0 {
            self.list_state.remeasure_items(0..count);
        }
    }

    /// Remeasure inline resources after their prepared content or metrics change.
    ///
    /// Call from the resource owner's completion handler, through a weak entity
    /// when the task can outlive this view. This does not reparse the document.
    /// Existing logical selection is retained until the next selection gesture.
    pub fn invalidate_inline_layout(&mut self, cx: &mut Context<Self>) {
        self.preserve_selection_for_reflow();
        cx.notify();
    }

    pub(super) fn preserve_selection_for_reflow(&mut self) {
        self.preserve_inline_selection = true;
        self.compatible_layout_update = true;
        self.invalidate_measured_heights();
    }

    fn increment_update(&mut self, text: &str, append: bool, cx: &mut Context<Self>) {
        self.revision += 1;
        if !append {
            self.full_update_revision = self.revision;
            self.selection_revision = self.selection_revision.wrapping_add(1);
            // Old native layouts must not project a still-active gesture back
            // into replaced content, including while a large parse is pending.
            self.selection_adapter.clear_copy_projections(cx);
            self.parsed_content.document.clear_selection();
        }
        let parse_synchronously = !append && text.len() <= MAX_SYNC_FULL_REPLACE_BYTES;
        let update_options = UpdateOptions {
            revision: self.revision,
            append,
            mode: if append {
                ParseMode::Compatible
            } else if parse_synchronously {
                ParseMode::BaselineAck
            } else {
                ParseMode::Replace
            },
            pending_text: text.to_string(),
            markdown_extensions: self.markdown_extensions.clone(),
        };

        // Keep small full replacements synchronous so their first layout has
        // the exact content height. Larger replacements use the existing
        // background parser, bounding synchronous parser input on the UI thread.
        if parse_synchronously {
            match parse_content(self.format, ParsedContent::default(), &update_options) {
                Ok(content) => {
                    self.reconcile_range_highlights(&content.document, self.revision, false);
                    self.stream_fade.record(
                        &self.parsed_content.document,
                        &content.document,
                        Instant::now(),
                    );
                    self.parsed_content = content;
                    self.parsed_error = None;
                    self.invalidate_measured_heights();
                    if !self.is_selecting {
                        self.reset_selection_and_adapter(cx);
                    }
                }
                Err(err) => {
                    self.stream_fade.discard_pending();
                    self.parsed_error = Some(err);
                }
            }
            // Keep the background parser's accumulated document in sync so a
            // later append extends this baseline instead of parsing the delta
            // as a standalone document.
            _ = self.tx.try_send(update_options);
            cx.notify();
            return;
        }

        _ = self.tx.try_send(update_options);
    }

    /// Whether [`Self::commit_parsed_update`] commits `parsed_update`: it is
    /// not older than what is committed or than the last replacement, nor
    /// the background parser acknowledging a synchronous parse.
    fn commits(&self, parsed_update: &ParsedUpdate) -> bool {
        if parsed_update.revision < self.full_update_revision
            || parsed_update.revision <= self.committed_revision
        {
            return false;
        }
        debug_assert!(!parsed_update.baseline_ack || parsed_update.full_parse);
        !parsed_update.baseline_ack
    }

    /// Commit a result of the background parser.
    ///
    /// A stream that appends faster than a parse completes has always moved
    /// past the revision the result was parsed from, so only discarding
    /// results of an older revision would show nothing until the stream
    /// stops. A result parsed since the text was last replaced is a prefix of
    /// the current text and is committed; one from before that replacement,
    /// or older than what is already committed, is discarded.
    fn commit_parsed_update(&mut self, parsed_update: ParsedUpdate, cx: &mut Context<Self>) {
        if !self.commits(&parsed_update) {
            return;
        }

        match parsed_update.result {
            Ok(content) => {
                let append = parsed_update.selection_compatible && !parsed_update.full_parse;
                if append && self.full_update_revision <= self.committed_revision {
                    self.splice_appended_blocks(&content.document);
                }
                self.reconcile_range_highlights(&content.document, parsed_update.revision, append);
                self.stream_fade.record(
                    &self.parsed_content.document,
                    &content.document,
                    Instant::now(),
                );
                // This result may cover only part of the queued appends.
                // Keep the uncommitted tail pending from this document's end,
                // rather than consuming its fade with the earlier chunk.
                if parsed_update.revision < self.revision {
                    self.stream_fade.note_extend(content.document.source.len());
                }
                self.parsed_content = content;
                self.parsed_error = None;
                self.compatible_layout_update = parsed_update.selection_compatible;
                if parsed_update.full_parse {
                    self.invalidate_measured_heights();
                }
            }
            Err(err) => {
                self.stream_fade.discard_pending();
                self.parsed_error = Some(err);
            }
        }
        // Don't interrupt an active drag-selection; the stored
        // positions remain valid for append-only updates and will
        // self-correct on the next mouse-move event.
        if !parsed_update.selection_compatible && !self.is_selecting {
            self.reset_selection_and_adapter(cx);
        }
        cx.notify();
    }

    /// The text this view renders, which [`RangeHighlight`] ranges index.
    ///
    /// This is the string plain copy produces, as of the last parse that
    /// landed; text set since then is not in it until its parse lands.
    pub fn rendered_text(&self) -> RenderedText {
        RenderedText::new(
            self.entity_id,
            self.committed_revision,
            self.parsed_content.document.clone(),
            self.rendered_index.clone(),
        )
    }

    /// Replace the range highlights, whose ranges index the current rendered text.
    ///
    /// Compute ranges from the current [`Self::rendered_text`] and set them in
    /// the same update. Search the new text again after its content changes.
    /// Ranges of the Markdown source, such as [`Self::selected_source_range`]
    /// returns, convert with [`RenderedText::range_for_source`].
    /// A range crossing blocks paints in both, skipping their separator.
    /// Text outside every block (separators, custom blocks, HTML blocks, and
    /// inline objects) is left unpainted. Any invalid range rejects the set.
    ///
    /// Highlights follow unchanged text through updates. Text appended while
    /// streaming keeps earlier highlights; after a table edit, cells in and
    /// after the edited row lose theirs because cells are known by position.
    /// Text backgrounds such as `<mark>` paint over a highlight; inline code
    /// backgrounds paint under it.
    pub fn set_range_highlights(
        &mut self,
        highlights: impl IntoIterator<Item = RangeHighlight>,
        cx: &mut Context<Self>,
    ) -> Result<(), RangeHighlightError> {
        if self.format != TextViewFormat::Markdown {
            return Err(RangeHighlightError::Unsupported);
        }
        let text = self.rendered_text();
        self.range_highlights = RangeHighlightFrame::new(&text, highlights)?.map(Arc::new);
        cx.notify();
        Ok(())
    }

    /// Scroll the line `range` starts on into view, `range` indexing the
    /// current rendered text, as with [`Self::set_range_highlights`].
    ///
    /// A [`Self::scrollable`] view scrolls itself. Otherwise the nearest
    /// enclosing `gpui::list` scrolls, as long as the row holding the view is
    /// laid out, so scroll to that row first when it may be off screen. Any
    /// other scroll container scrolls through
    /// [`TextView::on_reveal`](crate::text::TextView::on_reveal). An empty
    /// range reveals the line of its position; a range in text that belongs
    /// to no block's text, such as a custom block's, scrolls its whole block
    /// into a scrollable view.
    ///
    /// Only the latest reveal is carried out. It follows the content as
    /// [range highlights](Self::set_range_highlights) do, and it is dropped
    /// when its text changes, when the view clamps its lines, or when it
    /// cannot be shown within a second, so it never scrolls long after it
    /// was asked for. A whole block taller than the view, scrolled to from
    /// below, shows its end.
    ///
    /// Revealing is best effort: `Ok(())` means the range is valid for the
    /// current text and the request was taken, not that the view has
    /// scrolled. A dropped request is not reported.
    pub fn reveal_range(
        &mut self,
        range: Range<usize>,
        cx: &mut Context<Self>,
    ) -> Result<(), RangeHighlightError> {
        if self.format != TextViewFormat::Markdown {
            return Err(RangeHighlightError::Unsupported);
        }
        let text = self.rendered_text();
        if text.is_empty() && range == (0..0) {
            // Nothing to reveal in an empty view.
            self.pending_reveal = None;
            return Ok(());
        }
        let now = cx.background_executor().now();
        self.pending_reveal = Some(
            PendingReveal::new(&text, &range, now).ok_or(RangeHighlightError::InvalidRange(0))?,
        );
        cx.notify();
        Ok(())
    }

    /// Remove all range highlights.
    pub fn clear_range_highlights(&mut self, cx: &mut Context<Self>) {
        if self.range_highlights.take().is_some() {
            cx.notify();
        }
    }

    /// Carry the range highlights over to `new`, the document the update of
    /// `revision` parsed, before it replaces the current one.
    ///
    /// `append` is whether that update parsed only appended text onto the
    /// document before it. Only when no update has replaced the text since
    /// the current document was committed was that document the current one,
    /// so only then do the blocks before its last stay unchanged.
    fn reconcile_range_highlights(&mut self, new: &ParsedDocument, revision: usize, append: bool) {
        let tail_only = append && self.full_update_revision <= self.committed_revision;
        self.committed_revision = revision;
        self.rendered_index = Arc::default();
        if self.range_highlights.is_some() || self.pending_reveal.is_some() {
            let remap = LeafRemap::new(&self.parsed_content.document, new, tail_only);
            self.range_highlights = self
                .range_highlights
                .take()
                .and_then(|highlights| highlights.remap(&remap))
                .map(Arc::new);
            self.pending_reveal = self
                .pending_reveal
                .take()
                .and_then(|reveal| reveal.remap(&remap));
        }
    }

    /// Tell the scrollable list which blocks an append replaced, before `new`,
    /// the appended document, replaces the current one.
    ///
    /// An append parses only the current document's last block again, so the
    /// blocks before it keep their spans and their measured heights. Without
    /// this, `render_root` resets the list whenever the block count changes,
    /// which scrolled a streaming view back to the top and measured every
    /// block again on each new block. Only a grown block count is handled
    /// here; anything else is left to that reset.
    fn splice_appended_blocks(&self, new: &ParsedDocument) {
        let old = &self.parsed_content.document.blocks;
        let (old_count, new_count) = (old.len(), new.blocks.len());
        if old_count == 0 || new_count <= old_count || self.list_state.item_count() != old_count {
            return;
        }

        // The last block is always measured again: it was parsed again, and
        // it is no longer the last one.
        let unchanged = old
            .iter()
            .zip(new.blocks.iter())
            .take(old_count - 1)
            .take_while(|(old_block, new_block)| {
                old_block
                    .span()
                    .is_some_and(|span| new_block.span() == Some(span))
            })
            .count();
        // Keeps the replaced blocks' heights as hints and the scroll offset
        // inside them, and has the next layout measure only the blocks that
        // are not measured.
        self.list_state.remeasure_items(unchanged..old_count);
        self.list_state
            .splice(old_count..old_count, new_count - old_count);
    }

    /// Save bounds and unselect if bounds changed.
    pub(super) fn update_bounds(&mut self, bounds: Bounds<Pixels>, _cx: &mut App) {
        self.bounds = bounds;
    }

    /// The index of the top-level block at `content_y`, in this view's content
    /// coordinates (the same space the base selection endpoint stores its point in).
    ///
    /// Only laid-out blocks can be located, which is enough for a selection
    /// endpoint: the user can only put one where they can see it. Returns
    /// `None` for a view that is not virtualized, where every block paints and
    /// the range is not needed.
    pub(super) fn block_ix_at(&self, content_y: Pixels) -> Option<usize> {
        if !self.scrollable {
            return None;
        }

        let origin = self.bounds.origin.y + self.scroll_offset().y;
        let count = self.list_state.item_count();
        let mut ix = self.list_state.logical_scroll_top().item_ix;
        while ix < count {
            let bounds = self.list_state.bounds_for_item(ix)?;
            if content_y < bounds.bottom() - origin {
                return Some(ix);
            }
            ix += 1;
        }

        count.checked_sub(1)
    }

    #[doc(hidden)]
    pub fn bounds(&self) -> Bounds<Pixels> {
        self.bounds
    }

    #[doc(hidden)]
    pub fn list_state(&self) -> &ListState {
        &self.list_state
    }

    #[doc(hidden)]
    pub fn is_selecting(&self) -> bool {
        self.is_selecting
    }

    #[doc(hidden)]
    pub fn focus_handle(&self) -> &FocusHandle {
        &self.focus_handle
    }

    /// Whether this view has a view-local selection (select-all, multi-click, or override),
    /// independent of the window-level selection.
    pub(super) fn has_view_selection(&self) -> bool {
        self.select_all
            || self.multi_click_selection.is_some()
            || self.selected_text_override.is_some()
    }

    pub(super) fn stop_auto_scroll(&mut self) {
        self.auto_scroll.stop();
    }

    pub(super) fn reset_selection(&mut self) {
        self.preserve_inline_selection = false;
        self.multi_click_selection = None;
        self.selected_text_override = None;
        self.select_all = false;
        self.is_selecting = false;
        self.auto_scroll.stop();
        // Clear the inline selection state synchronously, so offscreen
        // (virtualized) views that won't repaint don't leak stale selection
        // text into a new cross-view copy.
        self.parsed_content.document.clear_selection();
    }

    fn reset_selection_and_adapter(&mut self, cx: &mut App) {
        self.reset_selection();
        self.selection_adapter.set_local_selection(false, cx);
    }

    /// Clear the current text selection.
    pub fn clear_selection(&mut self, cx: &mut Context<Self>) {
        self.reset_selection_and_adapter(cx);
        cx.notify();
    }

    pub(super) fn scroll_offset(&self) -> Point<Pixels> {
        if self.scrollable {
            self.list_state.scroll_px_offset_for_scrollbar()
        } else {
            Point::default()
        }
    }

    /// Select all rendered text in this view.
    pub fn select_all(&mut self, cx: &mut Context<Self>) {
        self.multi_click_selection = None;
        self.selected_text_override = None;
        self.select_all = true;
        self.is_selecting = false;
        self.auto_scroll.stop();
        self.selection_adapter.set_local_selection(true, cx);
        cx.notify();
    }

    /// Selects what a multi-click at `pos` selected, from the caret `start`
    /// to the caret `end` in window coordinates. A drag from the click
    /// extends it by the same unit.
    pub(crate) fn set_multi_click_selection(
        &mut self,
        pos: Point<Pixels>,
        kind: TextViewMultiClickKind,
        selected_text: String,
        (start, end): (Bounds<Pixels>, Bounds<Pixels>),
        cx: &mut App,
    ) {
        self.preserve_inline_selection = false;
        let scroll_offset = self.scroll_offset();
        let pos = pos - self.bounds.origin - scroll_offset;
        self.multi_click_selection = Some(TextViewMultiClickSelection {
            pos,
            kind,
            line_bounds: None,
        });
        self.selected_text_override = Some(selected_text);
        self.select_all = false;
        self.is_selecting = false;
        self.auto_scroll.stop();
        self.selection_adapter.set_local_selection(true, cx);
        let click_count = match kind {
            TextViewMultiClickKind::Word => 2,
            TextViewMultiClickKind::Paragraph | TextViewMultiClickKind::Line => 3,
        };
        self.selection_adapter
            .hold_multi_click(start, end, click_count, cx);
    }

    /// Hands a multi-click selection over to the window selection, which a
    /// drag from the click has taken beyond what the click selected.
    pub(super) fn end_multi_click_selection(&mut self, cx: &mut App) {
        if self.multi_click_selection.take().is_some() {
            self.selected_text_override = None;
            self.selection_adapter.set_local_selection(false, cx);
        }
    }

    pub(crate) fn set_multi_click_line(&mut self, bounds: Bounds<Pixels>, cx: &mut App) {
        self.set_multi_click_selection(
            bounds.center(),
            TextViewMultiClickKind::Line,
            String::new(),
            (
                caret_line_box(bounds.origin, bounds.size.height),
                caret_line_box(bounds.top_right(), bounds.size.height),
            ),
            cx,
        );
        self.selected_text_override = None;
        let offset = self.bounds.origin + self.scroll_offset();
        if let Some(selection) = self.multi_click_selection.as_mut() {
            selection.line_bounds = Some(Bounds::new(bounds.origin - offset, bounds.size));
        }
    }

    pub(super) fn set_auto_scroll(&mut self, delta: Option<Pixels>, cx: &mut Context<Self>) {
        self.auto_scroll.set(delta, cx, |delta, state, cx| {
            state.list_state.scroll_by(delta);
            cx.notify();
        });
    }

    /// Return the window selection (anchor, cursor) in window coordinates if
    /// this view participates in it.
    ///
    /// Single-view fast path: when both endpoints are anchored inside one
    /// TextView, only that view participates (identical to the previous
    /// per-view behavior).
    pub(crate) fn selection_points(&self, cx: &App) -> Option<(Point<Pixels>, Point<Pixels>)> {
        if !self.selectable {
            return None;
        }
        self.selection_adapter.selection_points(cx)
    }

    /// [`Self::selection_points`] for the text that paints now: a drag that
    /// started in a table cell selects only in that cell. Call it only while
    /// painting, so the cell the text is in is known.
    pub(crate) fn painted_selection_points(
        &self,
        cx: &App,
    ) -> Option<(Point<Pixels>, Point<Pixels>)> {
        if !self.selectable {
            return None;
        }
        self.selection_adapter.painted_selection_points(cx)
    }

    pub(crate) fn has_selection(&self, cx: &App) -> bool {
        self.has_view_selection() || self.selection_points(cx).is_some()
    }

    pub(super) fn on_action_select_all(
        &mut self,
        _: &SelectAll,
        _: &mut Window,
        cx: &mut Context<Self>,
    ) {
        if !self.selectable {
            cx.propagate();
            return;
        }

        self.select_all(cx);
    }

    pub(crate) fn is_selectable(&self) -> bool {
        self.selectable
    }

    pub(crate) fn is_all_selected(&self) -> bool {
        self.select_all
    }

    pub(crate) fn multi_click_selection(&self) -> Option<TextViewMultiClickSelection> {
        let scroll_offset = self.scroll_offset();
        self.multi_click_selection.map(|selection| {
            let pos = selection.pos + scroll_offset + self.bounds.origin;
            let line_bounds = selection.line_bounds.map(|bounds| {
                Bounds::new(
                    bounds.origin + scroll_offset + self.bounds.origin,
                    bounds.size,
                )
            });
            TextViewMultiClickSelection {
                pos,
                line_bounds,
                ..selection
            }
        })
    }
}

#[derive(Clone, Copy, Debug, PartialEq)]
pub(crate) struct TextViewMultiClickSelection {
    pub(crate) pos: Point<Pixels>,
    pub(crate) kind: TextViewMultiClickKind,
    pub(crate) line_bounds: Option<Bounds<Pixels>>,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub(crate) enum TextViewMultiClickKind {
    Word,
    Paragraph,
    Line,
}

impl TextViewState {
    /// Starts a frame of the pending reveal: the line to hand to rendering,
    /// and the block a scrollable view has to scroll to first, because it is
    /// off screen or the reveal is of a whole block.
    fn reveal_frame(
        &mut self,
        now: Instant,
        window: &mut Window,
    ) -> (Option<RevealRequest>, Option<usize>) {
        if self.max_lines.is_some()
            || self
                .pending_reveal
                .as_ref()
                .is_some_and(|reveal| reveal.is_expired(now))
        {
            self.pending_reveal = None;
        }
        let Some(pending) = &self.pending_reveal else {
            return (None, None);
        };

        let block_ix = pending.block_ix(&self.parsed_content.document);
        let block_off_screen = |ix: usize| {
            let viewport = self.list_state.viewport_bounds();
            self.list_state.bounds_for_item(ix).is_none_or(|item| {
                item.bottom() <= viewport.top() || item.top() >= viewport.bottom()
            })
        };
        let reveal_block = block_ix.filter(|ix| {
            self.scrollable
                && (pending.is_block() || !pending.was_laid_out())
                && block_off_screen(*ix)
        });
        let request = pending.request();
        if pending.is_block() {
            // A block has no line to wait for.
            self.pending_reveal = None;
        } else {
            window.request_animation_frame();
        }
        (request, reveal_block)
    }
}

impl Render for TextViewState {
    fn render(&mut self, window: &mut Window, cx: &mut Context<Self>) -> impl IntoElement {
        let typography = (window.text_style(), window.rem_size());
        let body_font_size = typography.0.font_size.to_pixels(typography.1);
        if self
            .layout_text_style
            .as_ref()
            .is_some_and(|previous| previous != &typography)
        {
            // ListState invalidates its cached rows for width changes, but does
            // not know that an inherited font or rem change affects offscreen
            // inline metrics. Retain logical selections just as for resources.
            self.preserve_selection_for_reflow();
        }
        self.layout_text_style = Some(typography);
        let state = cx.entity();
        let stream_fade = self.stream_fade.frame(Instant::now(), cx.reduce_motion());
        if stream_fade.is_some() && self.fade_tick.is_none() {
            self.fade_tick = Some(cx.spawn(async move |this, cx| {
                cx.background_executor().timer(STREAM_FADE_TICK).await;
                _ = this.update(cx, |state, cx| {
                    state.fade_tick = None;
                    cx.notify();
                });
            }));
        }
        let (reveal, reveal_block) = self.reveal_frame(cx.background_executor().now(), window);
        // Built every frame, so everything in it is shared, not copied.
        let node_cx = NodeContext {
            offset: self.parsed_content.node_cx.offset,
            link_refs: self.parsed_content.node_cx.link_refs.clone(),
            style: self.text_view_style.clone(),
            code_block_actions: self.code_block_actions.clone(),
            code_block_highlighter: self.code_block_highlighter.clone(),
            table_actions: self.table_actions.clone(),
            link_click_handler: self.link_click_handler.clone(),
            image_source: self.image_source.clone(),
            markdown_extensions: self.markdown_extensions.clone(),
            stream_fade,
            range_highlights: self.range_highlights.clone(),
            reveal,
            body_font_size,
        };

        let content = v_flex()
            .w_full()
            // Clamped content must keep its natural height: stretching it to
            // the capped box would hide the overflow the clamp has to measure.
            .when(self.max_lines.is_none(), |this| this.h_full())
            .map(|this| match &self.parsed_error {
                None => this.child(self.parsed_content.document.render_root(
                    if self.scrollable {
                        Some(self.list_state.clone())
                    } else {
                        None
                    },
                    &node_cx,
                    window,
                    cx,
                )),
                Some(err) => this.child(
                    v_flex()
                        .gap_1()
                        .child("Failed to parse content")
                        .child(err.to_string()),
                ),
            })
            .on_prepaint(move |bounds, window, cx| {
                let (
                    size_changed,
                    selection_involves_view,
                    has_selection_snapshot,
                    is_selecting,
                    compatible_layout_update,
                    preserve_width_selection,
                ) = {
                    let state = state.read(cx);
                    let has_selection_snapshot = state.selection_adapter.has_selection_snapshot(cx);
                    let preserve_width_selection = !state.is_selecting
                        && state.bounds().size.width != bounds.size.width
                        && (has_selection_snapshot || state.has_view_selection());
                    (
                        state.bounds().size != bounds.size,
                        state.selection_adapter.is_part_of_window_selection(cx),
                        has_selection_snapshot,
                        state.is_selecting,
                        // A measurement prepaint must not consume compatibility
                        // before the same entity's visible column prepaints.
                        state.compatible_layout_update
                            || preserve_width_selection
                            || state.preserve_inline_selection,
                        preserve_width_selection,
                    )
                };
                let mut revision_changed = false;
                state.update(cx, |state, cx| {
                    revision_changed = state
                        .selection_adapter
                        .update_layout_revision(state.selection_revision, state.is_selecting);
                    if preserve_width_selection {
                        // ListState already remeasures width changes. Arm logical
                        // retention before inline paint without invalidating rows again.
                        state.preserve_inline_selection = true;
                    }
                    state.update_bounds(bounds, cx);
                    state.compatible_layout_update = false;
                });
                if !is_selecting
                    && ((size_changed && selection_involves_view && !compatible_layout_update)
                        || (revision_changed && has_selection_snapshot))
                {
                    TextSelection::clear(window, cx);
                }
            });
        // After `render_root`, which resets the list when the block count
        // changed other than by an append, and with it the scroll position.
        if let Some(block_ix) = reveal_block {
            self.list_state.scroll_to_reveal_item(block_ix);
        }
        content
    }
}

#[derive(Clone, PartialEq, Default)]
pub(crate) struct ParsedContent {
    pub(crate) document: ParsedDocument,
    pub(crate) node_cx: node::NodeContext,
}

struct UpdateFuture {
    format: TextViewFormat,
    content: ParsedContent,
    rx: Pin<Box<Receiver<UpdateOptions>>>,
    tx_result: Sender<ParsedUpdate>,
}

impl UpdateFuture {
    fn new(
        format: TextViewFormat,
        rx: Receiver<UpdateOptions>,
        tx_result: Sender<ParsedUpdate>,
    ) -> Self {
        Self {
            format,
            content: Default::default(),
            rx: Box::pin(rx),
            tx_result,
        }
    }
}

impl Future for UpdateFuture {
    type Output = ();

    fn poll(mut self: Pin<&mut Self>, cx: &mut std::task::Context<'_>) -> Poll<Self::Output> {
        loop {
            match self.rx.as_mut().poll_next(cx) {
                Poll::Ready(Some(mut options)) => {
                    let hit_coalesce_budget =
                        merge_pending_options(&mut options, self.rx.as_ref().get_ref());

                    let res = parse_content(self.format, self.content.clone(), &options);
                    if let Ok(content) = &res {
                        self.content = content.clone();
                    }
                    _ = self.tx_result.try_send(ParsedUpdate {
                        revision: options.revision,
                        full_parse: !options.append,
                        selection_compatible: options.mode == ParseMode::Compatible,
                        baseline_ack: options.mode == ParseMode::BaselineAck,
                        result: res,
                    });
                    if hit_coalesce_budget {
                        cx.waker().wake_by_ref();
                        return Poll::Pending;
                    }
                    continue;
                }
                Poll::Ready(None) => return Poll::Ready(()),
                Poll::Pending => return Poll::Pending,
            }
        }
    }
}

#[derive(Clone)]
struct UpdateOptions {
    revision: usize,
    pending_text: String,
    append: bool,
    mode: ParseMode,
    markdown_extensions: Arc<MarkdownExtensions>,
}

impl UpdateOptions {
    fn merge(&mut self, next: UpdateOptions) {
        if next.append {
            self.pending_text.push_str(&next.pending_text);
            self.revision = next.revision;
            if self.mode != ParseMode::Replace {
                self.mode = ParseMode::Compatible;
            }
        } else {
            *self = next;
        }
    }
}

struct ParsedUpdate {
    revision: usize,
    full_parse: bool,
    selection_compatible: bool,
    baseline_ack: bool,
    result: Result<ParsedContent, SharedString>,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
enum ParseMode {
    BaselineAck,
    Replace,
    Compatible,
}

fn merge_pending_options(options: &mut UpdateOptions, rx: &Receiver<UpdateOptions>) -> bool {
    let mut update_count = 1;

    while update_count < MAX_COALESCED_UPDATES_PER_PARSE {
        match rx.try_recv() {
            Ok(next_options) => {
                options.merge(next_options);
                update_count += 1;
            }
            Err(_) => return false,
        }
    }

    true
}

fn parse_content(
    format: TextViewFormat,
    mut content: ParsedContent,
    options: &UpdateOptions,
) -> Result<ParsedContent, SharedString> {
    let mut node_cx = NodeContext {
        markdown_extensions: options.markdown_extensions.clone(),
        ..NodeContext::default()
    };

    // Re-parse the last block together with the appended text, so a block the
    // new text continues (an unclosed list, a fenced code block) is not split
    // in two. A block without a span cannot be located in `source` — the HTML
    // parser never records spans — so it is left in place and only the
    // appended text is parsed, positioned at the end of the current source.
    let last_span = options
        .append
        .then(|| {
            content
                .document
                .blocks
                .last()
                .and_then(|block| block.span())
        })
        .flatten();

    let mut source = String::new();
    if let Some(span) = last_span {
        Arc::make_mut(&mut content.document.blocks).pop();
        node_cx.offset = span.start;
        source.push_str(&content.document.source[span.start..]);
        source.push_str(&options.pending_text);
    } else {
        if options.append {
            node_cx.offset = content.document.source.len();
        }
        source.push_str(&options.pending_text);
    }

    let new_document = match format {
        TextViewFormat::Markdown => format::markdown::parse(&source, &mut node_cx),
        TextViewFormat::Html => format::html::parse(&source, &mut node_cx),
    }?;

    if options.append {
        content.document.source =
            format!("{}{}", content.document.source, options.pending_text).into();
        Arc::make_mut(&mut content.document.blocks)
            .extend(Arc::unwrap_or_clone(new_document.blocks));
    } else {
        content.document = new_document;
    }

    Ok(content)
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::text::{
        MarkdownNode,
        node::{BlockNode, Span},
    };
    use gpui::{Entity, TestAppContext};

    /// A view reading a text view state, inside a view notified on every
    /// frame, counting its renders.
    #[cfg(feature = "gpui-fast")]
    mod parse_ack {
        use std::{cell::Cell, rc::Rc};

        use gpui::{
            AppContext as _, Context, Entity, IntoElement, ParentElement as _, Render,
            TestAppContext, Window, div,
        };

        use super::super::TextViewState;

        struct Reader {
            state: Entity<TextViewState>,
            renders: Rc<Cell<usize>>,
        }

        impl Render for Reader {
            fn render(&mut self, _: &mut Window, cx: &mut Context<Self>) -> impl IntoElement {
                self.renders.set(self.renders.get() + 1);
                div().child(self.state.read(cx).text.clone())
            }
        }

        struct Holder {
            reader: Entity<Reader>,
        }

        impl Render for Holder {
            fn render(&mut self, _: &mut Window, _: &mut Context<Self>) -> impl IntoElement {
                div().child(self.reader.clone())
            }
        }

        /// The background parser acknowledging a text parsed as it was set
        /// commits nothing, and leaves the state alone: a view that read it,
        /// in a view notified for something else, is not built again.
        #[gpui::test]
        fn acknowledging_a_parse_leaves_its_readers_retained(cx: &mut TestAppContext) {
            cx.update(crate::init);
            let renders = Rc::new(Cell::new(0));
            let (holder, cx) = cx.add_window_view(|_, cx| Holder {
                reader: cx.new(|cx| Reader {
                    state: cx.new(|cx| TextViewState::markdown("Some **text**.", cx)),
                    renders: renders.clone(),
                }),
            });
            cx.update(|window, cx| window.draw(cx).clear(cx));
            let before = renders.get();
            cx.run_until_parked();
            holder.update(cx, |_, cx| cx.notify());
            cx.update(|window, cx| window.draw(cx).clear(cx));
            assert_eq!(renders.get(), before, "the reader rendered again");
        }
    }

    mod stream_fade {
        use std::{cell::Cell, ops::Range, rc::Rc, time::Duration};

        use gpui::{Entity, TestAppContext};

        use super::super::*;
        use crate::{motion::Easing, text::stream_fade::TextLeafKey};

        /// Long enough that a debug test cannot outrun the fade before it
        /// samples the first frame.
        const FADE: Duration = Duration::from_secs(10);

        fn fading_state(markdown: &str, cx: &mut TestAppContext) -> Entity<TextViewState> {
            cx.update(crate::init);
            let state = cx.update(|cx| {
                cx.new(|cx| {
                    TextViewState::markdown(markdown, cx).motion(
                        TextViewMotion::default()
                            .with_stream_fade(FADE)
                            .with_stream_fade_easing(Easing::Linear),
                    )
                })
            });
            cx.run_until_parked();
            state
        }

        /// The fade ranges of `key` sampled right now, or `None` when the
        /// state has nothing fading.
        fn fades(
            state: &Entity<TextViewState>,
            key: TextLeafKey,
            cx: &mut TestAppContext,
        ) -> Option<Vec<Range<usize>>> {
            state.update(cx, |state, _| {
                let frame = state.stream_fade.frame(Instant::now(), false)?;
                let fades = frame.fades(key)?;
                assert!(
                    fades.iter().all(|(_, fade_out)| *fade_out > 0.9),
                    "a fade sampled right after it starts is still transparent: {fades:?}"
                );
                Some(fades.iter().map(|(range, _)| range.clone()).collect())
            })
        }

        #[gpui::test]
        fn push_str_fades_only_the_appended_text(cx: &mut TestAppContext) {
            let state = fading_state("hello", cx);
            state.update(cx, |state, cx| state.push_str(" world", cx));
            cx.run_until_parked();

            assert_eq!(fades(&state, TextLeafKey::block(0), cx), Some(vec![5..11]));

            state.update(cx, |state, _| {
                let later = Instant::now() + FADE + Duration::from_secs(1);
                assert!(state.stream_fade.frame(later, false).is_none());
                assert!(state.stream_fade.frame(Instant::now(), false).is_none());
            });
        }

        #[gpui::test]
        fn overtaken_parse_preserves_the_remaining_chunks_fade(cx: &mut TestAppContext) {
            let state = fading_state("hello", cx);
            let parsed = super::push_and_parse(&state, " one", cx);
            state.update(cx, |state, cx| {
                state.push_str(" two", cx);
                state.commit_parsed_update(parsed, cx);
            });
            assert_eq!(fades(&state, TextLeafKey::block(0), cx), Some(vec![5..9]));

            cx.run_until_parked();
            assert_eq!(
                fades(&state, TextLeafKey::block(0), cx),
                Some(vec![5..9, 9..13])
            );
        }

        #[gpui::test]
        fn overtaken_parse_preserves_a_remaining_blocks_fade(cx: &mut TestAppContext) {
            let state = fading_state("hello", cx);
            let parsed = super::push_and_parse(&state, " one", cx);
            state.update(cx, |state, cx| {
                state.push_str("\n\nsecond", cx);
                state.commit_parsed_update(parsed, cx);
            });
            assert_eq!(fades(&state, TextLeafKey::block(0), cx), Some(vec![5..9]));

            // A third chunk arrives while the second is still uncommitted.
            state.update(cx, |state, cx| state.push_str(" third", cx));
            cx.run_until_parked();
            let ranges = fades(&state, TextLeafKey::block(11), cx).expect("new paragraph fades");
            assert_eq!(
                ranges.into_iter().flatten().collect::<Vec<_>>(),
                (0..12).collect::<Vec<_>>()
            );
        }

        #[gpui::test]
        fn set_text_extending_the_text_fades_like_push_str(cx: &mut TestAppContext) {
            let state = fading_state("hello", cx);
            state.update(cx, |state, cx| state.set_text("hello world", cx));
            cx.run_until_parked();

            assert_eq!(fades(&state, TextLeafKey::block(0), cx), Some(vec![5..11]));
        }

        #[gpui::test]
        fn set_text_replacing_the_text_shows_it_at_once(cx: &mut TestAppContext) {
            let state = fading_state("hello", cx);
            state.update(cx, |state, cx| state.push_str(" world", cx));
            cx.run_until_parked();
            assert!(fades(&state, TextLeafKey::block(0), cx).is_some());

            state.update(cx, |state, cx| state.set_text("other", cx));
            cx.run_until_parked();

            assert_eq!(fades(&state, TextLeafKey::block(0), cx), None);
        }

        #[gpui::test]
        fn completed_markup_refades_from_the_divergence(cx: &mut TestAppContext) {
            // The paragraph renders `text` (trailing space trimmed), then
            // `text **bo` literally.
            let state = fading_state("text ", cx);
            state.update(cx, |state, cx| state.push_str("**bo", cx));
            cx.run_until_parked();
            assert_eq!(fades(&state, TextLeafKey::block(0), cx), Some(vec![4..9]));

            // `text **bold**` renders `text bold`: the space keeps its fade,
            // the glyphs from byte 5 on changed and fade again as one run.
            state.update(cx, |state, cx| state.push_str("ld**", cx));
            cx.run_until_parked();
            assert_eq!(
                fades(&state, TextLeafKey::block(0), cx),
                Some(vec![4..5, 5..9])
            );
        }

        #[gpui::test]
        fn without_stagger_an_update_fades_as_one_chunk(cx: &mut TestAppContext) {
            let state = fading_state("hello", cx);
            state.update(cx, |state, cx| state.push_str(" one two three", cx));
            cx.run_until_parked();

            assert_eq!(fades(&state, TextLeafKey::block(0), cx), Some(vec![5..19]));
        }

        #[gpui::test]
        fn words_of_one_update_start_one_after_another(cx: &mut TestAppContext) {
            let stagger = Duration::from_millis(100);
            let state = fading_state("hello", cx);
            state.update(cx, |state, _| {
                state.set_motion(
                    TextViewMotion::default()
                        .with_stream_fade(FADE)
                        .with_stream_fade_stagger(stagger)
                        .with_stream_fade_easing(Easing::Linear),
                )
            });
            state.update(cx, |state, cx| state.push_str(" one two three", cx));
            cx.run_until_parked();

            state.update(cx, |state, _| {
                let frame = state
                    .stream_fade
                    .frame(Instant::now() + stagger * 3, false)
                    .expect("words still fading");
                let fades = frame.fades(TextLeafKey::block(0)).expect("paragraph fades");
                let ranges: Vec<_> = fades.iter().map(|(range, _)| range.clone()).collect();
                assert_eq!(ranges, vec![5..10, 10..14, 14..19]);
                // A later word has faded less, so it is still more transparent.
                assert!(
                    fades[0].1 < fades[1].1 && fades[1].1 < fades[2].1,
                    "{fades:?}"
                );
            });
        }

        #[gpui::test]
        fn a_new_paragraph_fades_as_a_whole(cx: &mut TestAppContext) {
            let state = fading_state("first", cx);
            state.update(cx, |state, cx| state.push_str("\n\nsecond", cx));
            cx.run_until_parked();

            assert_eq!(fades(&state, TextLeafKey::block(0), cx), None);
            assert_eq!(fades(&state, TextLeafKey::block(7), cx), Some(vec![0..6]));
        }

        #[gpui::test]
        fn code_block_text_fades_by_block(cx: &mut TestAppContext) {
            let state = fading_state("```rs\nlet", cx);
            state.update(cx, |state, cx| state.push_str(" x", cx));
            cx.run_until_parked();

            assert_eq!(fades(&state, TextLeafKey::block(0), cx), Some(vec![3..5]));
        }

        #[gpui::test]
        fn table_cells_fade_by_ordinal(cx: &mut TestAppContext) {
            let state = fading_state("| a | b |\n|---|---|\n| c | d", cx);
            state.update(cx, |state, cx| state.push_str("e |", cx));
            cx.run_until_parked();

            assert_eq!(fades(&state, TextLeafKey::table_cell(0, 2), cx), None);
            assert_eq!(
                fades(&state, TextLeafKey::table_cell(0, 3), cx),
                Some(vec![1..2])
            );
        }

        #[gpui::test]
        fn zero_duration_records_nothing(cx: &mut TestAppContext) {
            cx.update(crate::init);
            let state = cx.update(|cx| cx.new(|cx| TextViewState::markdown("hello", cx)));
            cx.run_until_parked();
            state.update(cx, |state, cx| state.push_str(" world", cx));
            cx.run_until_parked();

            state.update(cx, |state, _| {
                assert!(state.stream_fade.frame(Instant::now(), false).is_none());
            });
        }

        #[gpui::test]
        fn reduced_motion_drops_the_fade(cx: &mut TestAppContext) {
            let state = fading_state("hello", cx);
            state.update(cx, |state, cx| state.push_str(" world", cx));
            cx.run_until_parked();

            state.update(cx, |state, _| {
                assert!(state.stream_fade.frame(Instant::now(), true).is_none());
                assert!(state.stream_fade.frame(Instant::now(), false).is_none());
            });
        }

        #[gpui::test]
        fn a_fade_repaints_on_a_timer_until_nothing_fades(cx: &mut TestAppContext) {
            struct FadeRoot(Entity<TextViewState>);
            impl Render for FadeRoot {
                fn render(&mut self, _: &mut Window, _: &mut Context<Self>) -> impl IntoElement {
                    crate::text::TextView::new(&self.0)
                }
            }

            let state = fading_state("hello", cx);
            let (_, cx) = cx.add_window_view(|_, _| FadeRoot(state.clone()));
            let notifies = Rc::new(Cell::new(0));
            let _subscription = cx.update(|_, cx| {
                let notifies = notifies.clone();
                cx.observe(&state, move |_, _| notifies.set(notifies.get() + 1))
            });

            state.update(cx, |state, cx| state.push_str(" world", cx));
            cx.run_until_parked();
            cx.update(|window, cx| window.draw(cx).clear(cx));
            let before = notifies.get();

            cx.executor().advance_clock(STREAM_FADE_TICK / 2);
            cx.run_until_parked();
            assert_eq!(notifies.get(), before);

            // Each tick repaints once, and that frame schedules the next tick.
            for tick in 1..=3 {
                cx.executor().advance_clock(STREAM_FADE_TICK);
                cx.run_until_parked();
                assert_eq!(notifies.get(), before + tick);
            }

            // Replacing the text drops the fade, so the ticks stop.
            state.update(cx, |state, cx| state.set_text("other", cx));
            cx.run_until_parked();
            cx.executor().advance_clock(STREAM_FADE_TICK);
            cx.run_until_parked();
            let after = notifies.get();
            cx.executor().advance_clock(STREAM_FADE_TICK * 10);
            cx.run_until_parked();
            assert_eq!(notifies.get(), after);
            assert!(state.read_with(cx, |state, _| state.fade_tick.is_none()));
        }
    }

    #[gpui::test]
    fn small_full_replace_parses_before_background_executor_runs(cx: &mut TestAppContext) {
        cx.update(crate::init);
        let markdown = "# ready";
        let state = cx.update(|cx| cx.new(|cx| TextViewState::markdown(markdown, cx)));

        state.read_with(cx, |state, _| {
            assert_eq!(state.source().as_str(), markdown);
            assert_eq!(state.parsed_content.document.blocks.len(), 1);
        });
    }

    #[gpui::test]
    fn large_markdown_and_html_full_replacements_wait_for_background_executor(
        cx: &mut TestAppContext,
    ) {
        cx.update(crate::init);
        let markdown = "# x\n\n".repeat(MAX_SYNC_FULL_REPLACE_BYTES / 5 + 1);
        let html = format!("<p>{}</p>", "x".repeat(MAX_SYNC_FULL_REPLACE_BYTES + 1));
        assert!(markdown.len() > MAX_SYNC_FULL_REPLACE_BYTES);
        assert!(html.len() > MAX_SYNC_FULL_REPLACE_BYTES);

        let (markdown_state, html_state) = cx.update(|cx| {
            (
                cx.new(|cx| TextViewState::markdown(&markdown, cx)),
                cx.new(|cx| TextViewState::html(&html, cx)),
            )
        });

        markdown_state.read_with(cx, |state, _| {
            assert_eq!(state.text.as_str(), markdown.as_str());
            assert!(state.source().as_str().is_empty());
            assert!(state.parsed_content.document.blocks.is_empty());
        });
        html_state.read_with(cx, |state, _| {
            assert_eq!(state.text.as_str(), html.as_str());
            assert!(state.source().as_str().is_empty());
            assert!(state.parsed_content.document.blocks.is_empty());
        });

        cx.run_until_parked();

        markdown_state.read_with(cx, |state, _| {
            assert_eq!(state.source().as_str(), markdown.as_str());
            assert!(!state.parsed_content.document.blocks.is_empty());
        });
        html_state.read_with(cx, |state, _| {
            assert_eq!(state.source().as_str(), html.as_str());
            assert!(!state.parsed_content.document.blocks.is_empty());
        });
    }

    #[gpui::test]
    fn inline_source_ranges_follow_streamed_tail_reparsing(cx: &mut TestAppContext) {
        cx.update(crate::init);
        let state = cx.update(|cx| cx.new(|cx| TextViewState::markdown("中文 $a$\n\n尾 $x", cx)));
        state.update(cx, |state, cx| {
            let extensions = MarkdownExtensions::default().plugin(
                crate::text::markdown_ext::TestInlinePlugin::new("test").parse_with(|node, _| {
                    let markdown::mdast::Node::InlineMath(math) = node else {
                        return None;
                    };
                    Some(super::super::MarkdownNode::new("formula", ()).text(math.value.clone()))
                }),
            );
            state.set_markdown_extensions(Arc::new(extensions), cx);
        });
        cx.run_until_parked();
        state.update(cx, |state, cx| state.push_str("^2$ 后", cx));
        cx.run_until_parked();
        state.read_with(cx, |state, _| {
            let source = "中文 $a$\n\n尾 $x^2$ 后";
            assert_eq!(state.source().as_str(), source);
            let objects: Vec<_> = state
                .parsed_content
                .document
                .blocks
                .iter()
                .flat_map(|block| {
                    let super::super::node::BlockNode::Paragraph(paragraph) = block else {
                        panic!()
                    };
                    paragraph
                        .children
                        .iter()
                        .filter_map(|node| node.custom.as_ref())
                })
                .collect();
            assert_eq!(objects.len(), 2);
            for (object, markdown) in objects.iter().zip(["$a$", "$x^2$"]) {
                let start = source.find(markdown).unwrap();
                assert_eq!(object.source_range(), Some(start..start + markdown.len()));
                assert_eq!(object.as_markdown(), markdown);
            }
        });
    }

    #[gpui::test]
    fn async_full_replace_then_push_str_preserves_complete_source(cx: &mut TestAppContext) {
        cx.update(crate::init);
        let state = cx.update(|cx| cx.new(|cx| TextViewState::markdown("old", cx)));
        cx.run_until_parked();

        let replacement = "x".repeat(MAX_SYNC_FULL_REPLACE_BYTES + 1);
        let expected = format!("{replacement} tail");
        state.update(cx, |state, cx| {
            state.set_text(&replacement, cx);
            state.push_str(" tail", cx);
        });
        cx.run_until_parked();

        state.read_with(cx, |state, _| {
            assert_eq!(state.text.as_str(), expected.as_str());
            assert_eq!(state.source().as_str(), expected.as_str());
        });
    }

    /// Push `chunk` and parse it the way the background parser would, without
    /// running the parser, returning the update it would send.
    fn push_and_parse(
        state: &Entity<TextViewState>,
        chunk: &str,
        cx: &mut TestAppContext,
    ) -> ParsedUpdate {
        let (revision, baseline) = state.update(cx, |state, cx| {
            state.push_str(chunk, cx);
            (state.revision, state.parsed_content.clone())
        });
        let options = UpdateOptions {
            revision,
            pending_text: chunk.to_string(),
            append: true,
            mode: ParseMode::Compatible,
            markdown_extensions: Arc::default(),
        };
        ParsedUpdate {
            revision,
            full_parse: false,
            selection_compatible: true,
            baseline_ack: false,
            result: parse_content(TextViewFormat::Markdown, baseline, &options),
        }
    }

    #[gpui::test]
    fn stream_commits_a_parse_that_a_newer_chunk_overtook(cx: &mut TestAppContext) {
        cx.update(crate::init);
        let state = cx.update(|cx| cx.new(|cx| TextViewState::markdown("# Answer\n\n", cx)));
        cx.run_until_parked();

        // Chunks arriving faster than they parse always push the next chunk
        // before the previous parse lands.
        let parsed = push_and_parse(&state, "Streaming", cx);
        state.update(cx, |state, cx| {
            state.push_str(" tokens", cx);
            state.commit_parsed_update(parsed, cx);
            assert_eq!(state.source().as_str(), "# Answer\n\nStreaming");
        });

        cx.run_until_parked();
        state.read_with(cx, |state, _| {
            assert_eq!(state.source().as_str(), "# Answer\n\nStreaming tokens");
        });
    }

    #[gpui::test]
    fn a_parse_from_before_a_replacement_is_discarded(cx: &mut TestAppContext) {
        cx.update(crate::init);
        let state = cx.update(|cx| cx.new(|cx| TextViewState::markdown("old", cx)));
        cx.run_until_parked();

        let parsed = push_and_parse(&state, " text", cx);
        // Large enough to parse in the background, so the replacement is not
        // committed yet when the older parse lands.
        let replacement = "x".repeat(MAX_SYNC_FULL_REPLACE_BYTES + 1);
        state.update(cx, |state, cx| {
            state.set_text(&replacement, cx);
            state.commit_parsed_update(parsed, cx);
            assert_eq!(state.source().as_str(), "old");
        });

        cx.run_until_parked();
        state.read_with(cx, |state, _| {
            assert_eq!(state.source().as_str(), replacement.as_str());
        });
    }

    #[gpui::test]
    fn html_push_str_keeps_earlier_blocks(cx: &mut TestAppContext) {
        cx.update(crate::init);
        let state = cx.update(|cx| cx.new(|cx| TextViewState::html("<p>first</p>", cx)));
        cx.run_until_parked();

        state.update(cx, |state, cx| {
            state.push_str("<p>second</p>", cx);
        });
        cx.run_until_parked();

        state.read_with(cx, |state, _| {
            assert_eq!(state.source().as_str(), "<p>first</p><p>second</p>");
            let text = state
                .parsed_content
                .document
                .blocks
                .iter()
                .map(|block| block.text())
                .collect::<String>();
            assert!(text.contains("first"), "lost the first block: {text:?}");
            assert!(text.contains("second"), "lost the appended block: {text:?}");
        });
    }

    #[gpui::test]
    fn element_text_of_the_same_string_is_not_compared_again(cx: &mut TestAppContext) {
        cx.update(crate::init);
        let state = cx.update(|cx| cx.new(|cx| TextViewState::markdown("", cx)));
        let revision = |cx: &mut TestAppContext| state.read_with(cx, |state, _| state.revision);
        let text = SharedString::from("hello");

        state.update(cx, |state, cx| state.set_element_text(&text, cx));
        let parsed = revision(cx);
        assert!(parsed > 0);

        // The same allocation again, and equal bytes in another allocation,
        // both leave the parsed text alone.
        state.update(cx, |state, cx| state.set_element_text(&text, cx));
        assert_eq!(revision(cx), parsed);
        let equal = SharedString::from("hello".to_string());
        state.update(cx, |state, cx| state.set_element_text(&equal, cx));
        assert_eq!(revision(cx), parsed);

        // Once the state's text moved on, the element's string is set again.
        state.update(cx, |state, cx| {
            state.push_str(" world", cx);
            state.set_element_text(&equal, cx);
        });
        state.read_with(cx, |state, _| assert_eq!(state.text.as_str(), "hello"));
    }

    #[gpui::test]
    fn set_text_then_push_str_appends_to_replaced_content(cx: &mut TestAppContext) {
        cx.update(crate::init);
        let state = cx.update(|cx| cx.new(|cx| TextViewState::markdown("old", cx)));
        cx.run_until_parked();

        state.update(cx, |state, cx| {
            state.set_text("", cx);
            state.push_str("new", cx);
            state.push_str(" text", cx);
        });
        cx.run_until_parked();

        state.read_with(cx, |state, _| {
            assert_eq!(state.text.as_str(), "new text");
            assert_eq!(state.source().as_str(), "new text");
        });

        state.update(cx, |state, cx| {
            state.set_text("", cx);
        });
        cx.run_until_parked();

        state.read_with(cx, |state, _| {
            assert_eq!(state.text.as_str(), "");
            assert_eq!(state.source().as_str(), "");
        });
    }

    #[gpui::test]
    fn full_parse_coalesced_with_append_preserves_new_select_all(cx: &mut TestAppContext) {
        cx.update(crate::init);
        let state = cx.update(|cx| cx.new(|cx| TextViewState::markdown("old", cx)));
        cx.run_until_parked();

        state.update(cx, |state, cx| {
            state.set_text("new", cx);
            state.push_str(" text", cx);
            state.select_all(cx);
        });
        cx.run_until_parked();

        state.read_with(cx, |state, _| {
            assert!(state.select_all);
            assert_eq!(state.selected_text().trim(), "new text");
        });
    }

    fn parsed_blocks(
        state: &Entity<TextViewState>,
        cx: &mut TestAppContext,
    ) -> Vec<(String, Option<Span>)> {
        state.read_with(cx, |state, _| {
            state
                .parsed_content
                .document
                .blocks
                .iter()
                .map(|block| (block.text(), block.span()))
                .collect()
        })
    }

    #[gpui::test]
    fn set_text_extending_markdown_appends_and_keeps_selection(cx: &mut TestAppContext) {
        cx.update(crate::init);
        let state = cx.update(|cx| cx.new(|cx| TextViewState::markdown("hello", cx)));
        cx.run_until_parked();
        let revisions =
            |state: &TextViewState| (state.selection_revision, state.full_update_revision);
        let initial = state.read_with(cx, |state, _| revisions(state));

        state.update(cx, |state, cx| state.set_text("hello world", cx));
        cx.run_until_parked();
        state.read_with(cx, |state, _| {
            assert_eq!(state.source().as_str(), "hello world");
            assert_eq!(revisions(state), initial);
        });

        state.update(cx, |state, cx| state.set_text("hello", cx));
        cx.run_until_parked();
        state.read_with(cx, |state, _| {
            assert_eq!(state.source().as_str(), "hello");
            assert_ne!(state.selection_revision, initial.0);
            assert_ne!(state.full_update_revision, initial.1);
        });
    }

    #[gpui::test]
    fn set_text_streaming_markdown_matches_a_full_parse(cx: &mut TestAppContext) {
        cx.update(crate::init);
        let streamed = cx.update(|cx| cx.new(|cx| TextViewState::markdown("# Title", cx)));
        cx.run_until_parked();

        // Chunks continue a heading, a paragraph, an inline code span, a list
        // and a fenced code block, and the text grows past the synchronous
        // parse limit.
        let filler = "word ".repeat(MAX_SYNC_FULL_REPLACE_BYTES / 5 + 1);
        let chunks = [
            "\n\nfirst para",
            "graph with `co",
            "de`\n\n- one\n",
            "- two\n\n```rust\nfn main() {",
            "}\n```\n\n",
            filler.as_str(),
            "\n\nlast",
        ];
        let full_update_revision = streamed.read_with(cx, |state, _| state.full_update_revision);
        let mut text = "# Title".to_string();
        for chunk in chunks {
            text.push_str(chunk);
            streamed.update(cx, |state, cx| state.set_text(&text, cx));
            cx.run_until_parked();
        }
        assert_eq!(
            streamed.read_with(cx, |state, _| state.full_update_revision),
            full_update_revision
        );

        let parsed = cx.update(|cx| cx.new(|cx| TextViewState::markdown(&text, cx)));
        cx.run_until_parked();

        assert_eq!(
            streamed.read_with(cx, |state, _| state.source()),
            parsed.read_with(cx, |state, _| state.source())
        );
        assert_eq!(parsed_blocks(&streamed, cx), parsed_blocks(&parsed, cx));
    }

    #[gpui::test]
    fn set_text_extending_html_parses_it_again(cx: &mut TestAppContext) {
        cx.update(crate::init);
        let streamed = cx.update(|cx| cx.new(|cx| TextViewState::html("<ul><li>a</li>", cx)));
        cx.run_until_parked();

        let text = "<ul><li>a</li><li>b</li></ul>";
        streamed.update(cx, |state, cx| state.set_text(text, cx));
        cx.run_until_parked();
        assert_ne!(
            streamed.read_with(cx, |state, _| state.full_update_revision),
            0
        );

        let parsed = cx.update(|cx| cx.new(|cx| TextViewState::html(text, cx)));
        cx.run_until_parked();
        assert_eq!(parsed_blocks(&streamed, cx), parsed_blocks(&parsed, cx));
    }

    #[gpui::test]
    fn set_text_extending_after_a_parse_error_parses_it_again(cx: &mut TestAppContext) {
        cx.update(crate::init);
        let state = cx.update(|cx| cx.new(|cx| TextViewState::markdown("hello", cx)));
        cx.run_until_parked();

        let full_update_revision = state.read_with(cx, |state, _| state.full_update_revision);

        state.update(cx, |state, cx| {
            state.parsed_error = Some("failed".into());
            state.set_text("hello world", cx);
        });
        cx.run_until_parked();

        state.read_with(cx, |state, _| {
            assert!(state.parsed_error.is_none());
            assert_ne!(state.full_update_revision, full_update_revision);
            assert_eq!(state.source().as_str(), "hello world");
        });
    }

    #[test]
    fn update_options_merge_keeps_latest_full_text() {
        let mut options = UpdateOptions {
            revision: 1,
            pending_text: "old".to_string(),
            append: true,
            mode: ParseMode::Compatible,
            markdown_extensions: Arc::default(),
        };

        options.merge(UpdateOptions {
            revision: 2,
            pending_text: "new".to_string(),
            append: false,
            mode: ParseMode::BaselineAck,
            markdown_extensions: Arc::default(),
        });
        options.merge(UpdateOptions {
            revision: 3,
            pending_text: " text".to_string(),
            append: true,
            mode: ParseMode::Compatible,
            markdown_extensions: Arc::default(),
        });

        assert_eq!(options.revision, 3);
        assert_eq!(options.pending_text, "new text");
        assert!(!options.append);
    }

    #[test]
    fn append_merged_into_async_replace_remains_a_replacement() {
        let mut options = UpdateOptions {
            revision: 1,
            pending_text: "new".to_string(),
            append: false,
            mode: ParseMode::Replace,
            markdown_extensions: Arc::default(),
        };

        options.merge(UpdateOptions {
            revision: 2,
            pending_text: " text".to_string(),
            append: true,
            mode: ParseMode::Compatible,
            markdown_extensions: Arc::default(),
        });

        assert_eq!(options.revision, 2);
        assert_eq!(options.pending_text, "new text");
        assert!(!options.append);
        assert_eq!(options.mode, ParseMode::Replace);
    }

    #[test]
    fn update_future_yields_before_coalescing_all_queued_updates() {
        let (tx, rx) = unbounded::<UpdateOptions>();
        let (tx_result, rx_result) = unbounded::<ParsedUpdate>();
        let total_updates = 128;

        for revision in 1..=total_updates {
            tx.try_send(UpdateOptions {
                revision,
                pending_text: format!("{revision}\n"),
                append: revision != 1,
                mode: if revision == 1 {
                    ParseMode::BaselineAck
                } else {
                    ParseMode::Compatible
                },
                markdown_extensions: Arc::default(),
            })
            .unwrap();
        }

        let mut future = Box::pin(UpdateFuture::new(TextViewFormat::Markdown, rx, tx_result));
        let waker = futures::task::noop_waker();
        let mut task_cx = std::task::Context::from_waker(&waker);

        assert!(matches!(
            std::future::Future::poll(future.as_mut(), &mut task_cx),
            Poll::Pending
        ));
        let parsed_update = rx_result.try_recv().expect("parse result");

        assert!(
            parsed_update.revision < total_updates,
            "single poll coalesced every queued update through revision {}",
            parsed_update.revision
        );

        assert!(matches!(
            std::future::Future::poll(future.as_mut(), &mut task_cx),
            Poll::Pending
        ));
        let parsed_update = rx_result.try_recv().expect("next parse result");
        assert_eq!(parsed_update.revision, total_updates);
    }

    #[gpui::test]
    fn select_all_returns_rendered_text(cx: &mut TestAppContext) {
        cx.update(crate::init);
        let state = cx.update(|cx| cx.new(|cx| TextViewState::markdown("**quick** value", cx)));
        cx.run_until_parked();

        state.update(cx, |state, cx| {
            state.select_all(cx);
        });

        state.read_with(cx, |state, _| {
            assert!(state.has_view_selection());
            assert_eq!(state.selected_text().trim(), "quick value");
        });

        state.update(cx, |state, cx| {
            state.clear_selection(cx);
        });

        state.read_with(cx, |state, _| {
            assert!(!state.has_view_selection());
            assert_eq!(state.selected_text(), "");
        });
    }

    #[gpui::test]
    fn select_all_in_source_format_returns_source(cx: &mut TestAppContext) {
        cx.update(crate::init);
        let markdown = "**quick** value";
        let state = cx.update(|cx| cx.new(|cx| TextViewState::markdown(markdown, cx)));
        cx.run_until_parked();

        state.update(cx, |state, cx| state.select_all(cx));

        // The default (plain) mode strips the markup.
        state.read_with(cx, |state, _| {
            assert_eq!(state.selected_text().trim(), "quick value");
        });

        state.update(cx, |state, cx| {
            state.set_selection_format(SelectionFormat::Source, cx)
        });

        // Source mode yields the whole source verbatim.
        state.read_with(cx, |state, _| {
            assert_eq!(state.selected_text().trim(), markdown);
        });
    }

    #[gpui::test]
    fn selected_source_range_returns_full_markdown_source_for_select_all(cx: &mut TestAppContext) {
        cx.update(crate::init);
        let markdown = "**quick** value";
        let state = cx.update(|cx| cx.new(|cx| TextViewState::markdown(markdown, cx)));
        cx.run_until_parked();

        state.update(cx, |state, cx| state.select_all(cx));

        state.read_with(cx, |state, _| {
            assert_eq!(state.selected_source_range(), Some(0..markdown.len()));
        });
    }

    #[gpui::test]
    fn selected_source_range_returns_none_for_html(cx: &mut TestAppContext) {
        cx.update(crate::init);
        let state = cx.update(|cx| cx.new(|cx| TextViewState::html("<b>quick</b>", cx)));
        cx.run_until_parked();

        state.update(cx, |state, cx| state.select_all(cx));

        state.read_with(cx, |state, _| {
            assert_eq!(state.selected_source_range(), None);
        });
    }

    #[test]
    fn selected_source_range_keeps_global_offsets_after_incremental_tail_parse() {
        let options = UpdateOptions {
            revision: 1,
            pending_text: "first\n\nsecond".to_string(),
            append: false,
            mode: ParseMode::Replace,
            markdown_extensions: Arc::default(),
        };
        let content = parse_content(TextViewFormat::Markdown, ParsedContent::default(), &options)
            .expect("initial parse");
        let content = parse_content(
            TextViewFormat::Markdown,
            content,
            &UpdateOptions {
                revision: 2,
                pending_text: "\n\n**écho**".to_string(),
                append: true,
                mode: ParseMode::Compatible,
                markdown_extensions: Arc::default(),
            },
        )
        .expect("incremental parse");
        let BlockNode::Paragraph(paragraph) = &content.document.blocks[2] else {
            panic!("expected appended paragraph");
        };
        let mut state = paragraph.state.lock().unwrap();
        state.set_text(paragraph.text().into());
        state.selection = Some((0.."écho".len()).into());
        drop(state);

        assert_eq!(content.document.selected_source_range(), Some(17..22));
    }

    #[test]
    fn streamed_ordered_list_continuation_preserves_start() {
        let initial = parse_content(
            TextViewFormat::Markdown,
            ParsedContent::default(),
            &UpdateOptions {
                revision: 1,
                pending_text: "3. three".to_string(),
                append: false,
                mode: ParseMode::Replace,
                markdown_extensions: Arc::default(),
            },
        )
        .expect("initial list parse");
        let continued = parse_content(
            TextViewFormat::Markdown,
            initial,
            &UpdateOptions {
                revision: 2,
                pending_text: "\n4. four".to_string(),
                append: true,
                mode: ParseMode::Compatible,
                markdown_extensions: Arc::default(),
            },
        )
        .expect("streamed list continuation parse");

        let BlockNode::List {
            start, children, ..
        } = &continued.document.blocks[0]
        else {
            panic!("expected streamed ordered list");
        };
        assert_eq!(*start, Some(3));
        assert_eq!(children.len(), 2);
    }

    #[gpui::test]
    fn parser_revision_reparses_same_name_inline_configuration(cx: &mut TestAppContext) {
        cx.update(crate::init);
        let state = cx.update(|cx| cx.new(|cx| TextViewState::markdown("@member", cx)));
        for (revision, label) in [(1, "Alice"), (2, "Bob")] {
            let extensions = MarkdownExtensions::default()
                .parser_revision(revision)
                .plugin(
                    crate::text::markdown_ext::TestInlinePlugin::new("test").parse_with(
                        move |node, _| {
                            matches!(node, markdown::mdast::Node::Text(_))
                                .then(|| MarkdownNode::new("mention", label).text(label))
                        },
                    ),
                );
            state.update(cx, |state, cx| {
                state.set_markdown_extensions(Arc::new(extensions), cx)
            });
            cx.run_until_parked();
            state.read_with(cx, |state, _| {
                let node::BlockNode::Paragraph(paragraph) =
                    &state.parsed_content.document.blocks[0]
                else {
                    panic!()
                };
                assert_eq!(
                    paragraph.children[0].custom.as_ref().unwrap().as_text(),
                    label
                );
            });
        }
    }

    #[gpui::test]
    fn set_markdown_extensions_reparses_existing_text(cx: &mut TestAppContext) {
        cx.update(crate::init);
        let state = cx.update(|cx| cx.new(|cx| TextViewState::markdown("$TSLA.US", cx)));
        cx.run_until_parked();

        let extensions = MarkdownExtensions::default().block_parser(|node, cx| {
            let markdown::mdast::Node::Paragraph(paragraph) = node else {
                return None;
            };
            let [markdown::mdast::Node::Text(text)] = paragraph.children.as_slice() else {
                return None;
            };
            let symbol = text.value.strip_prefix('$')?.to_string();
            let node_text = format!("${symbol}");

            Some(
                MarkdownNode::new("ticker", symbol)
                    .text(node_text)
                    .markdown(cx.node_source(node).unwrap_or_default()),
            )
        });

        state.update(cx, |state, cx| {
            state.set_markdown_extensions(Arc::new(extensions), cx);
        });
        cx.run_until_parked();

        state.read_with(cx, |state, _| {
            let node::BlockNode::Custom { node, .. } = &state.parsed_content.document.blocks[0]
            else {
                panic!("expected custom markdown node");
            };
            assert_eq!(node.name(), "ticker");
            assert_eq!(node.data::<String>().map(String::as_str), Some("TSLA.US"));
        });
    }

    mod range_highlights {
        use std::ops::Range;

        use gpui::{Entity, TestAppContext};

        use super::super::*;
        use crate::text::stream_fade::TextLeafKey;

        fn state(markdown: &str, cx: &mut TestAppContext) -> Entity<TextViewState> {
            cx.update(crate::init);
            let state = cx.update(|cx| cx.new(|cx| TextViewState::markdown(markdown, cx)));
            cx.run_until_parked();
            state
        }

        fn highlight(range: Range<usize>) -> RangeHighlight {
            RangeHighlight::new(range, gpui::hsla(0.15, 1., 0.5, 0.4))
        }

        /// Highlights `ranges` of the current rendered text.
        fn set(
            state: &Entity<TextViewState>,
            ranges: impl IntoIterator<Item = Range<usize>>,
            cx: &mut TestAppContext,
        ) -> Result<(), RangeHighlightError> {
            state.update(cx, |state, cx| {
                state.set_range_highlights(ranges.into_iter().map(highlight), cx)
            })
        }

        /// The ranges leaf `key` paints, in its own byte space.
        fn painted(
            state: &Entity<TextViewState>,
            key: TextLeafKey,
            cx: &mut TestAppContext,
        ) -> Vec<Range<usize>> {
            state.read_with(cx, |state, _| {
                state.range_highlights.as_ref().map_or(Vec::new(), |frame| {
                    frame
                        .backgrounds(key)
                        .iter()
                        .map(|(range, _)| range.clone())
                        .collect()
                })
            })
        }

        fn has_highlights(state: &Entity<TextViewState>, cx: &mut TestAppContext) -> bool {
            state.read_with(cx, |state, _| state.range_highlights.is_some())
        }

        #[gpui::test]
        fn rendered_text_is_the_plain_copy_text(cx: &mut TestAppContext) {
            let state = state(
                "# Title\n\nhello **world** \\*\n\n- item\n\n| a | b |\n|---|---|\n| c | d |\n\n```\nlet x\n```",
                cx,
            );
            state.read_with(cx, |state, _| {
                assert_eq!(
                    state.rendered_text().as_str(),
                    "Title\nhello world *\nitem\na b\nc d\n\nlet x\n"
                );
            });
        }

        #[gpui::test]
        fn a_match_across_marks_paints_in_its_paragraph(cx: &mut TestAppContext) {
            let state = state("hello **world**", cx);
            set(&state, [0.."hello world".len()], cx).unwrap();
            assert_eq!(painted(&state, TextLeafKey::block(0), cx), [0..11]);
        }

        #[gpui::test]
        fn repeated_text_maps_to_the_occurrence_addressed(cx: &mut TestAppContext) {
            let state = state("foo\n\nfoo", cx);
            let second = state.read_with(cx, |state, _| {
                state.rendered_text().as_str().rfind("foo").unwrap()
            });
            set(&state, [second..second + 3], cx).unwrap();
            assert!(painted(&state, TextLeafKey::block(0), cx).is_empty());
            assert_eq!(painted(&state, TextLeafKey::block(5), cx), [0..3]);
        }

        #[gpui::test]
        fn a_range_across_blocks_skips_the_separator(cx: &mut TestAppContext) {
            let state = state("ab\n\ncd", cx);
            // "ab\ncd\n": 1..4 is "b\nc".
            set(&state, [1..4], cx).unwrap();
            assert_eq!(painted(&state, TextLeafKey::block(0), cx), [1..2]);
            assert_eq!(painted(&state, TextLeafKey::block(4), cx), [0..1]);
        }

        #[gpui::test]
        fn table_cells_and_code_blocks_are_leaves(cx: &mut TestAppContext) {
            let state = state("| a | b |\n|---|---|\n| c | d |\n\n```\nlet x\n```", cx);
            // "a b\nc d\n\nlet x\n"
            set(&state, [0..3, 6..7, 9..12], cx).unwrap();
            assert_eq!(painted(&state, TextLeafKey::table_cell(0, 0), cx), [0..1]);
            assert_eq!(painted(&state, TextLeafKey::table_cell(0, 1), cx), [0..1]);
            assert_eq!(painted(&state, TextLeafKey::table_cell(0, 3), cx), [0..1]);
            let code_start = "| a | b |\n|---|---|\n| c | d |\n\n".len();
            assert_eq!(painted(&state, TextLeafKey::block(code_start), cx), [0..3]);
        }

        #[gpui::test]
        fn invalid_ranges_reject_the_whole_set(cx: &mut TestAppContext) {
            let state = state("中文\n\nab", cx);
            // "中文\nab\n"
            set(&state, [0.."中".len()], cx).unwrap();
            let invalid = [Range { start: 6, end: 3 }, 0..1, 0..100];
            for range in invalid {
                assert_eq!(
                    set(&state, [0..3, range.clone()], cx),
                    Err(RangeHighlightError::InvalidRange(1)),
                    "{range:?}"
                );
            }
            // The rejected sets left the earlier highlight in place.
            assert_eq!(painted(&state, TextLeafKey::block(0), cx), [0..3]);
        }

        #[gpui::test]
        fn text_outside_every_block_is_left_unpainted(cx: &mut TestAppContext) {
            let source = "foo one\n\n<div>foo two</div>\n\n| foo | x |\n|---|---|\n\nfoo three";
            let state = state(source, cx);
            let text = state.read_with(cx, |state, _| state.rendered_text().as_str().to_string());
            // Every "foo" and " ", an empty range, and the separator after the
            // first block: the HTML block's text and the separators are not
            // any block's text, so they paint nothing, but nothing fails.
            let ranges = text
                .match_indices("foo")
                .chain(text.match_indices(' '))
                .map(|(start, found)| start..start + found.len())
                .chain([3..3, 7..8])
                .collect::<Vec<_>>();
            set(&state, ranges, cx).unwrap();
            assert_eq!(painted(&state, TextLeafKey::block(0), cx), [0..3, 3..4]);
            let table = source.find("| foo").unwrap();
            assert_eq!(
                painted(&state, TextLeafKey::table_cell(table, 0), cx),
                [0..3]
            );
            let last = source.find("foo three").unwrap();
            assert_eq!(painted(&state, TextLeafKey::block(last), cx), [0..3, 3..4]);
        }

        #[gpui::test]
        fn a_later_highlight_paints_over_an_earlier_one(cx: &mut TestAppContext) {
            let state = state("abcdef", cx);
            set(&state, [0..6, 2..3], cx).unwrap();
            assert_eq!(painted(&state, TextLeafKey::block(0), cx), [0..6, 2..3]);
        }

        #[gpui::test]
        fn html_text_is_unsupported(cx: &mut TestAppContext) {
            let html = cx.update(|cx| cx.new(|cx| TextViewState::html("<p>one</p>", cx)));
            cx.run_until_parked();
            html.update(cx, |html, cx| {
                assert_eq!(
                    html.set_range_highlights([highlight(0..3)], cx),
                    Err(RangeHighlightError::Unsupported)
                );
            });
        }

        #[gpui::test]
        fn inline_objects_are_skipped(cx: &mut TestAppContext) {
            let state = state("x $a$ y", cx);
            state.update(cx, |state, cx| {
                let extensions = MarkdownExtensions::default().plugin(
                    crate::text::markdown_ext::TestInlinePlugin::new("test").parse_with(
                        |node, _| {
                            let markdown::mdast::Node::InlineMath(math) = node else {
                                return None;
                            };
                            Some(
                                crate::text::MarkdownNode::new("formula", ())
                                    .text(math.value.clone()),
                            )
                        },
                    ),
                );
                state.set_markdown_extensions(Arc::new(extensions), cx);
            });
            cx.run_until_parked();
            // "x a y\n", where "a" is the formula.
            set(&state, [2..3], cx).unwrap();
            assert!(painted(&state, TextLeafKey::block(0), cx).is_empty());
            set(&state, [0..5], cx).unwrap();
            assert_eq!(painted(&state, TextLeafKey::block(0), cx), [0..2, 3..5]);
        }

        #[gpui::test]
        fn push_str_keeps_earlier_blocks_and_clips_the_changed_tail(cx: &mut TestAppContext) {
            let state = state("first\n\na **b", cx);
            // "first\na **b\n"
            set(&state, [0..5, 6..11], cx).unwrap();

            // Closing the emphasis renders the tail as "a bc".
            state.update(cx, |state, cx| state.push_str("c**", cx));
            cx.run_until_parked();

            assert_eq!(painted(&state, TextLeafKey::block(0), cx), [0..5]);
            assert_eq!(painted(&state, TextLeafKey::block(7), cx), [0..2]);
        }

        #[gpui::test]
        fn push_str_keeps_a_block_whose_text_is_unchanged(cx: &mut TestAppContext) {
            let state = state("first\n\nsecond", cx);
            set(&state, [6..12], cx).unwrap();
            // A setext underline turns the paragraph into a heading at the
            // same source start, rendering the same text.
            state.update(cx, |state, cx| state.push_str("\n===", cx));
            cx.run_until_parked();
            assert_eq!(painted(&state, TextLeafKey::block(7), cx), [0..6]);
        }

        #[gpui::test]
        fn push_str_drops_highlights_of_a_leaf_that_is_gone(cx: &mut TestAppContext) {
            let state = state("first\n\n| a |", cx);
            set(&state, [0..5, 6..11], cx).unwrap();
            // A delimiter row turns the paragraph into a table, whose text
            // lives in cells instead.
            state.update(cx, |state, cx| state.push_str("\n|---|", cx));
            cx.run_until_parked();
            assert_eq!(painted(&state, TextLeafKey::block(0), cx), [0..5]);
            assert!(painted(&state, TextLeafKey::block(7), cx).is_empty());
            assert!(painted(&state, TextLeafKey::table_cell(7, 0), cx).is_empty());
        }

        #[gpui::test]
        fn replacing_text_drops_highlights_only_where_it_changed(cx: &mut TestAppContext) {
            let state = state("first\n\nsecond", cx);
            set(&state, [0..5, 6..12], cx).unwrap();
            state.update(cx, |state, cx| state.set_text("first\n\nchanged", cx));
            cx.run_until_parked();
            assert_eq!(painted(&state, TextLeafKey::block(0), cx), [0..5]);
            assert!(painted(&state, TextLeafKey::block(7), cx).is_empty());

            let large = "x".repeat(MAX_SYNC_FULL_REPLACE_BYTES + 1);
            state.update(cx, |state, cx| state.set_text(&large, cx));
            cx.run_until_parked();
            assert!(!has_highlights(&state, cx));
        }

        #[gpui::test]
        fn a_highlight_follows_its_block_past_an_earlier_edit(cx: &mut TestAppContext) {
            let state = state("foo\n\nbar\n\nbar", cx);
            // "foo\nbar\nbar\n": the first "bar", in the block at source 5.
            set(&state, [4..7], cx).unwrap();
            // Deleting "foo" moves that "bar" to 0, and the second one to 5.
            state.update(cx, |state, cx| state.set_text("bar\n\nbar", cx));
            cx.run_until_parked();
            assert_eq!(painted(&state, TextLeafKey::block(0), cx), [0..3]);
            assert!(painted(&state, TextLeafKey::block(5), cx).is_empty());

            let state = self::state("ERROR a\n\nERROR b\n\nERROR c", cx);
            set(&state, [8..15], cx).unwrap();
            state.update(cx, |state, cx| state.set_text("ERROR b\n\nERROR c", cx));
            cx.run_until_parked();
            assert_eq!(painted(&state, TextLeafKey::block(0), cx), [0..7]);
            assert!(painted(&state, TextLeafKey::block(9), cx).is_empty());
        }

        #[gpui::test]
        fn appending_a_copy_of_the_last_block_keeps_the_highlight_on_it(cx: &mut TestAppContext) {
            let state = state("a\n\nfoo", cx);
            // "a\nfoo\n"
            set(&state, [2..5], cx).unwrap();
            state.update(cx, |state, cx| state.set_text("a\n\nfoo\n\nfoo", cx));
            cx.run_until_parked();
            assert_eq!(painted(&state, TextLeafKey::block(3), cx), [0..3]);
            assert!(painted(&state, TextLeafKey::block(8), cx).is_empty());
        }

        #[gpui::test]
        fn deleting_a_table_row_drops_highlights_in_the_rows_it_moves(cx: &mut TestAppContext) {
            let table = "| a | b |\n|---|---|\n| x | 1 |\n| x | 2 |";
            let without_middle_row = "| a | b |\n|---|---|\n| x | 2 |";
            // "a b\nx 1\nx 2\n\n": the last row's cells, then the middle
            // row's "x".
            for ranges in [vec![8..9, 10..11], vec![4..5]] {
                let state = state(table, cx);
                set(&state, [0..1].into_iter().chain(ranges), cx).unwrap();
                state.update(cx, |state, cx| state.set_text(without_middle_row, cx));
                cx.run_until_parked();
                assert_eq!(painted(&state, TextLeafKey::table_cell(0, 0), cx), [0..1]);
                for cell in 1..4 {
                    assert!(
                        painted(&state, TextLeafKey::table_cell(0, cell), cx).is_empty(),
                        "cell {cell}"
                    );
                }
            }
        }

        #[gpui::test]
        fn streaming_table_rows_keeps_the_highlights_of_earlier_rows(cx: &mut TestAppContext) {
            let state = state("| a | b |\n|---|---|\n| x | 1 |", cx);
            // "a b\nx 1\n\n"
            set(&state, [0..1, 4..5], cx).unwrap();
            state.update(cx, |state, cx| {
                state.set_text("| a | b |\n|---|---|\n| x | 1 |\n| y | 2 |", cx)
            });
            cx.run_until_parked();
            assert_eq!(painted(&state, TextLeafKey::table_cell(0, 0), cx), [0..1]);
            assert_eq!(painted(&state, TextLeafKey::table_cell(0, 2), cx), [0..1]);
        }

        #[gpui::test]
        fn an_edit_in_an_earlier_block_keeps_later_highlights(cx: &mut TestAppContext) {
            let state = state("one\n\ntwo", cx);
            set(&state, [0..3, 4..7], cx).unwrap();
            state.update(cx, |state, cx| state.set_text("one!\n\ntwo", cx));
            cx.run_until_parked();
            assert_eq!(painted(&state, TextLeafKey::block(0), cx), [0..3]);
            assert_eq!(painted(&state, TextLeafKey::block(6), cx), [0..3]);
        }

        #[gpui::test]
        fn an_append_after_a_full_update_compares_every_block(cx: &mut TestAppContext) {
            let state = state("first\n\nsecond", cx);
            set(&state, [0..5], cx).unwrap();
            // An append result whose baseline was a full update that has not
            // been committed: its earlier blocks are not the current ones.
            let options = UpdateOptions {
                revision: 0,
                pending_text: "FIRST\n\nsecond".to_string(),
                append: false,
                mode: ParseMode::Replace,
                markdown_extensions: Arc::default(),
            };
            let new = parse_content(TextViewFormat::Markdown, ParsedContent::default(), &options)
                .unwrap()
                .document;
            state.update(cx, |state, _| {
                state.full_update_revision = state.committed_revision + 1;
                let revision = state.committed_revision + 2;
                state.reconcile_range_highlights(&new, revision, true);
            });
            assert!(!has_highlights(&state, cx));
        }

        #[gpui::test]
        fn streaming_through_set_text_keeps_highlights(cx: &mut TestAppContext) {
            let state = state("first\n\nsec", cx);
            // "first\nsec\n"
            set(&state, [0..5, 6..9], cx).unwrap();
            state.update(cx, |state, cx| state.set_text("first\n\nsecond", cx));
            cx.run_until_parked();
            assert_eq!(painted(&state, TextLeafKey::block(0), cx), [0..5]);
            assert_eq!(painted(&state, TextLeafKey::block(7), cx), [0..3]);
        }

        #[gpui::test]
        fn a_full_parse_merged_with_an_append_compares_every_block(cx: &mut TestAppContext) {
            let state = state("", cx);
            // The small text is committed at once, and its background parse
            // merges with the append into one full parse, in which the
            // definition turns the earlier `[foo]` into the link text `foo`.
            state.update(cx, |state, cx| {
                state.set_text("[foo] and some text\n\nmore", cx);
                let text = state.rendered_text();
                let some = text.as_str().find("some").unwrap();
                state
                    .set_range_highlights([highlight(some..some + 4)], cx)
                    .unwrap();
                state.push_str("\n\n[foo]: https://example.com", cx);
            });
            cx.run_until_parked();
            state.read_with(cx, |state, _| {
                assert!(state.rendered_text().as_str().starts_with("foo and some"));
            });
            assert!(painted(&state, TextLeafKey::block(0), cx).is_empty());
        }

        #[gpui::test]
        fn a_full_update_before_an_append_drops_replaced_highlights(cx: &mut TestAppContext) {
            let state = state("first", cx);
            set(&state, [0..5], cx).unwrap();
            let large = "x".repeat(MAX_SYNC_FULL_REPLACE_BYTES + 1);
            state.update(cx, |state, cx| {
                state.set_text(&large, cx);
                state.push_str(" tail", cx);
            });
            cx.run_until_parked();
            assert!(!has_highlights(&state, cx));
        }

        #[gpui::test]
        fn reparsing_unchanged_text_keeps_highlights(cx: &mut TestAppContext) {
            let state = state("first", cx);
            set(&state, [0..5], cx).unwrap();
            state.update(cx, |state, cx| {
                state.set_markdown_extensions(
                    Arc::new(MarkdownExtensions::default().parser_revision(1)),
                    cx,
                )
            });
            cx.run_until_parked();
            assert_eq!(painted(&state, TextLeafKey::block(0), cx), [0..5]);
        }

        pub(super) struct Root {
            pub(super) state: Entity<TextViewState>,
        }

        impl Render for Root {
            fn render(&mut self, _: &mut Window, _: &mut Context<Self>) -> impl IntoElement {
                gpui::div()
                    .w(px(120.))
                    .child(crate::text::TextView::new(&self.state).selectable(true))
            }
        }

        #[gpui::test]
        fn highlights_paint_across_inline_code_tables_and_code_blocks(cx: &mut TestAppContext) {
            cx.update(crate::init);
            let markdown = "wrapping text with `inline code` and a [link](https://x.y) \
                            that wraps\n\n| a | b |\n|---|---|\n| c | d |\n\n```\nlet x = 1;\n```";
            let (root, cx) = cx.add_window_view(|_, cx| Root {
                state: cx.new(|cx| TextViewState::markdown(markdown, cx)),
            });
            cx.run_until_parked();
            let state = root.read_with(cx, |root, _| root.state.clone());
            let text = state.read_with(cx, |state, _| state.rendered_text().as_str().to_string());
            let code = text.find("code").unwrap();
            let len = text.len();
            // Part of the inline code, every character, and the whole text.
            let ranges = [code..code + 2]
                .into_iter()
                .chain(text.char_indices().map(|(ix, c)| ix..ix + c.len_utf8()))
                .chain([0..len])
                .filter(|range| !text[range.clone()].trim().is_empty());
            state.update(cx, |state, cx| {
                state
                    .set_range_highlights(ranges.map(highlight), cx)
                    .unwrap();
            });
            cx.update(|window, cx| window.draw(cx).clear(cx));
            assert_eq!(
                painted(&state, TextLeafKey::block(0), cx)[0],
                code..code + 2
            );
        }

        /// The ranges of the current rendered text converted from `sources`.
        fn converted(
            state: &Entity<TextViewState>,
            sources: impl IntoIterator<Item = Range<usize>>,
            cx: &mut TestAppContext,
        ) -> Vec<Option<Range<usize>>> {
            state.read_with(cx, |state, _| {
                let text = state.rendered_text();
                sources
                    .into_iter()
                    .map(|source| text.range_for_source(source))
                    .collect()
            })
        }

        fn find(haystack: &str, needle: &str) -> Range<usize> {
            let start = haystack.find(needle).unwrap();
            start..start + needle.len()
        }

        #[gpui::test]
        fn source_ranges_highlight_the_text_rendered_from_them(cx: &mut TestAppContext) {
            let markdown =
                "In Rust, we use `u128` to handle **larger** numbers\n\n| a | **b** |\n|---|---|";
            let state = state(markdown, cx);
            state.update(cx, |state, cx| {
                let text = state.rendered_text();
                assert_eq!(text.source(), markdown);
                let highlights = ["`u128` to handle **larger**", "**b**"]
                    .into_iter()
                    .map(|needle| text.range_for_source(find(markdown, needle)).unwrap())
                    .map(highlight)
                    .collect::<Vec<_>>();
                state.set_range_highlights(highlights, cx).unwrap();
            });
            let rendered = "In Rust, we use u128 to handle larger numbers";
            assert_eq!(
                painted(&state, TextLeafKey::block(0), cx),
                [find(rendered, "u128 to handle larger")]
            );
            let table = markdown.find("| a").unwrap();
            assert_eq!(
                painted(&state, TextLeafKey::table_cell(table, 1), cx),
                [0..1]
            );
        }

        #[gpui::test]
        fn select_all_converts_to_every_rendered_character(cx: &mut TestAppContext) {
            let markdown = "# Title\n\nhello **world**\n\n- item";
            let state = state(markdown, cx);
            state.update(cx, |state, cx| state.select_all(cx));
            state.read_with(cx, |state, _| {
                let text = state.rendered_text();
                assert_eq!(text.as_str(), "Title\nhello world\nitem\n");
                let source = state.selected_source_range().unwrap();
                // All but the separator after the last block.
                assert_eq!(text.range_for_source(source), Some(0..text.len() - 1));
            });
        }

        #[gpui::test]
        fn a_snapshot_converts_against_its_own_source(cx: &mut TestAppContext) {
            let state = state("first", cx);
            let before = state.read_with(cx, |state, _| state.rendered_text());
            state.update(cx, |state, cx| state.push_str("\n\nsecond **part**", cx));
            let source = "first\n\nsecond **part**";
            let second = find(source, "second **part**");

            // The append is parsed in the background, so until it lands the
            // view renders the source it had.
            state.read_with(cx, |state, _| {
                let text = state.rendered_text();
                assert_eq!(text, before);
                assert_eq!(text.source(), "first");
                assert_eq!(text.range_for_source(second.clone()), None);
            });
            cx.run_until_parked();

            assert_eq!(
                converted(&state, [second.clone(), 0..5], cx),
                [Some(6..17), Some(0..5)]
            );
            state.read_with(cx, |state, _| {
                let text = state.rendered_text();
                assert_ne!(text, before);
                assert_eq!(text.source(), source);
                assert_eq!(&text.as_str()[6..17], "second part");
            });
            // An earlier snapshot keeps converting against its own source.
            assert_eq!(before.source(), "first");
            assert_eq!(before.range_for_source(0..5), Some(0..5));
            assert_eq!(before.range_for_source(second), None);
        }

        #[gpui::test]
        fn appended_blocks_convert_at_their_place_in_the_whole_source(cx: &mut TestAppContext) {
            let state = state("first\n\nsecond", cx);
            // The tail parse reparses from the last block, whose positions
            // must still count from the start of the whole source.
            state.update(cx, |state, cx| state.push_str(" more\n\n**écho** end", cx));
            cx.run_until_parked();
            let source = "first\n\nsecond more\n\n**écho** end";
            let converted = converted(
                &state,
                [
                    find(source, "second more"),
                    find(source, "**écho**"),
                    find(source, "end"),
                ],
                cx,
            );
            state.read_with(cx, |state, _| {
                let text = state.rendered_text();
                assert_eq!(text.source(), source);
                let texts = converted
                    .into_iter()
                    .map(|range| &text.as_str()[range.unwrap()])
                    .collect::<Vec<_>>();
                assert_eq!(texts, ["second more", "écho", "end"]);
            });
        }

        #[gpui::test]
        fn a_background_parse_converts_once_it_lands(cx: &mut TestAppContext) {
            cx.update(crate::init);
            let markdown = format!(
                "{}\n\n**tail**",
                "word ".repeat(MAX_SYNC_FULL_REPLACE_BYTES / 4)
            );
            let state = cx.update(|cx| cx.new(|cx| TextViewState::markdown(&markdown, cx)));
            let tail = find(&markdown, "**tail**");
            state.read_with(cx, |state, _| {
                let text = state.rendered_text();
                assert!(text.source().is_empty());
                assert!(text.is_empty());
                assert_eq!(text.range_for_source(tail.clone()), None);
            });
            cx.run_until_parked();
            state.read_with(cx, |state, _| {
                let text = state.rendered_text();
                assert_eq!(text.source(), markdown);
                let range = text.range_for_source(tail).unwrap();
                assert_eq!(&text.as_str()[range], "tail");
            });
        }

        #[gpui::test]
        fn inline_objects_convert_whole_and_stay_unpainted(cx: &mut TestAppContext) {
            let markdown = "x $ab$ y";
            let state = state(markdown, cx);
            state.update(cx, |state, cx| {
                let extensions = MarkdownExtensions::default().plugin(
                    crate::text::markdown_ext::TestInlinePlugin::new("test").parse_with(
                        |node, _| {
                            let markdown::mdast::Node::InlineMath(math) = node else {
                                return None;
                            };
                            Some(
                                crate::text::MarkdownNode::new("formula", ())
                                    .text(math.value.clone()),
                            )
                        },
                    ),
                );
                state.set_markdown_extensions(Arc::new(extensions), cx);
            });
            cx.run_until_parked();
            // "x ab y\n", where "ab" is the formula.
            let formula = find(markdown, "$ab$");
            assert_eq!(
                converted(
                    &state,
                    [
                        formula.clone(),
                        formula.start + 1..formula.start + 2,
                        0..markdown.len(),
                        find(markdown, "ab$ y"),
                    ],
                    cx
                ),
                [Some(2..4), Some(2..4), Some(0..6), Some(2..6)]
            );
            let ranges = converted(&state, [formula, 0..markdown.len()], cx);
            set(&state, [ranges[0].clone().unwrap()], cx).unwrap();
            assert!(painted(&state, TextLeafKey::block(0), cx).is_empty());
            set(&state, [ranges[1].clone().unwrap()], cx).unwrap();
            assert_eq!(painted(&state, TextLeafKey::block(0), cx), [0..2, 4..6]);
        }

        #[gpui::test]
        fn a_dragged_selection_highlights_through_its_source_range(cx: &mut TestAppContext) {
            struct SelectionRoot {
                state: Entity<TextViewState>,
            }

            impl Render for SelectionRoot {
                fn render(&mut self, _: &mut Window, _: &mut Context<Self>) -> impl IntoElement {
                    gpui::div()
                        .w(px(160.))
                        .child(crate::TextSelectionLayer)
                        .child(crate::text::TextView::new(&self.state))
                }
            }

            cx.update(crate::init);
            let markdown = "hello **world** and `code` &amp; more";
            let (root, cx) = cx.add_window_view(|_, cx| SelectionRoot {
                state: cx.new(|cx| TextViewState::markdown(markdown, cx)),
            });
            cx.run_until_parked();
            let state = root.read_with(cx, |root, _| root.state.clone());
            cx.update(|window, cx| window.draw(cx).clear(cx));
            let bounds = state.read_with(cx, |state, _| state.bounds());
            assert!(bounds.size.height > px(30.), "the text wraps, {bounds:?}");
            let start = bounds.origin + gpui::point(px(2.), px(4.));
            let end = bounds.bottom_right() - gpui::point(px(2.), px(4.));
            cx.simulate_mouse_down(start, gpui::MouseButton::Left, gpui::Modifiers::default());
            cx.update(|window, cx| window.draw(cx).clear(cx));
            cx.simulate_mouse_move(end, gpui::MouseButton::Left, gpui::Modifiers::default());
            cx.update(|window, cx| window.draw(cx).clear(cx));
            cx.simulate_mouse_up(end, gpui::MouseButton::Left, gpui::Modifiers::default());
            cx.update(|window, cx| window.draw(cx).clear(cx));

            let range = state.update(cx, |state, cx| {
                let selected = state.selected_text();
                let source = state
                    .selected_source_range()
                    .expect("selection maps to source");
                let text = state.rendered_text();
                let range = text.range_for_source(source).expect("source renders text");
                assert!(selected.contains("code &"), "selected {selected:?}");
                assert_eq!(
                    &text.as_str()[range.clone()],
                    selected.trim_end_matches('\n')
                );
                state.clear_selection(cx);
                state
                    .set_range_highlights([highlight(range.clone())], cx)
                    .unwrap();
                range
            });
            cx.update(|window, cx| window.draw(cx).clear(cx));
            assert_eq!(painted(&state, TextLeafKey::block(0), cx), [range]);
        }

        #[gpui::test]
        fn html_views_convert_no_source(cx: &mut TestAppContext) {
            let html = cx.update(|cx| cx.new(|cx| TextViewState::html("<p>one</p>", cx)));
            cx.run_until_parked();
            html.read_with(cx, |html, _| {
                let text = html.rendered_text();
                assert_eq!(text.source(), "<p>one</p>");
                assert_eq!(text.range_for_source(0..10), None);
                assert_eq!(text.range_for_source(3..6), None);
            });
        }

        #[gpui::test]
        fn clear_range_highlights_removes_them(cx: &mut TestAppContext) {
            let state = state("first", cx);
            set(&state, [0..5], cx).unwrap();
            state.update(cx, |state, cx| state.clear_range_highlights(cx));
            assert!(!has_highlights(&state, cx));
        }
    }

    mod reveal_range {
        use gpui::{
            Entity, InteractiveElement as _, ListAlignment, ListState, ScrollHandle,
            StatefulInteractiveElement as _, TestAppContext, VisualTestContext, div, list,
        };

        use super::super::*;
        use crate::text::TextView;

        /// Where the view sits in a 200 × 100 window.
        #[derive(Clone)]
        enum Container {
            /// A scrollable view.
            Scrollable,
            /// A fit-content view, second row of an application list.
            List(ListState),
            /// A fit-content view in a scrolling `div`, which follows reveals
            /// through `on_reveal`.
            Div(ScrollHandle),
            /// A fit-content view clamped to two lines, second row of a list.
            Clamped(ListState),
            /// A fit-content view in nothing that scrolls.
            Fixed,
        }

        struct Root {
            state: Entity<TextViewState>,
            container: Container,
        }

        impl Render for Root {
            fn render(&mut self, _: &mut Window, _: &mut Context<Self>) -> impl IntoElement {
                let state = self.state.clone();
                let frame = div().w(px(200.)).h(px(100.));
                let row = |list_state: &ListState, clamp: bool| {
                    let state = state.clone();
                    list(list_state.clone(), move |ix, _, _| match ix {
                        0 => div().h(px(40.)).into_any_element(),
                        _ => TextView::new(&state)
                            .when(clamp, |view| view.max_lines(2))
                            .into_any_element(),
                    })
                    .size_full()
                };
                match &self.container {
                    Container::Scrollable => frame
                        .child(TextView::new(&state).scrollable(true))
                        .into_any_element(),
                    Container::List(list_state) => {
                        frame.child(row(list_state, false)).into_any_element()
                    }
                    Container::Clamped(list_state) => {
                        frame.child(row(list_state, true)).into_any_element()
                    }
                    Container::Div(handle) => {
                        let scroll = handle.clone();
                        frame
                            .child(
                                div()
                                    .id("scroll")
                                    .size_full()
                                    .overflow_y_scroll()
                                    .track_scroll(handle)
                                    .child(TextView::new(&state).on_reveal(move |line, _, _| {
                                        let viewport = scroll.bounds();
                                        let mut offset = scroll.offset();
                                        if line.bottom() > viewport.bottom() {
                                            offset.y -= line.bottom() - viewport.bottom();
                                        } else if line.top() < viewport.top() {
                                            offset.y += viewport.top() - line.top();
                                        }
                                        scroll.set_offset(offset);
                                    })),
                            )
                            .into_any_element()
                    }
                    Container::Fixed => frame.child(TextView::new(&state)).into_any_element(),
                }
            }
        }

        fn window<'a>(
            markdown: &str,
            container: Container,
            cx: &'a mut TestAppContext,
        ) -> (Entity<TextViewState>, &'a mut VisualTestContext) {
            cx.update(crate::init);
            let (root, cx) = cx.add_window_view(|_, cx| Root {
                state: cx.new(|cx| TextViewState::markdown(markdown, cx)),
                container,
            });
            cx.run_until_parked();
            draw(cx);
            let state = root.read_with(cx, |root, _| root.state.clone());
            (state, cx)
        }

        fn draw(cx: &mut VisualTestContext) {
            cx.update(|window, cx| window.draw(cx).clear(cx));
        }

        /// Asks to reveal the first occurrence of `needle`, then runs `then`
        /// before anything is drawn.
        fn request(
            state: &Entity<TextViewState>,
            needle: &str,
            cx: &mut VisualTestContext,
            then: impl FnOnce(&mut TextViewState, &mut Context<TextViewState>),
        ) {
            state.update(cx, |state, cx| {
                let text = state.rendered_text();
                let start = text.as_str().find(needle).unwrap();
                state.reveal_range(start..start + needle.len(), cx).unwrap();
                then(state, cx);
            });
        }

        /// Reveals the first occurrence of `needle` and draws a few frames.
        fn reveal(state: &Entity<TextViewState>, needle: &str, cx: &mut VisualTestContext) {
            request(state, needle, cx, |_, _| {});
            for _ in 0..3 {
                draw(cx);
            }
        }

        fn is_pending(state: &Entity<TextViewState>, cx: &mut VisualTestContext) -> bool {
            state.read_with(cx, |state, _| state.pending_reveal.is_some())
        }

        fn scroll_top(
            state: &Entity<TextViewState>,
            cx: &mut VisualTestContext,
        ) -> gpui::ListOffset {
            state.read_with(cx, |state, _| state.list_state.logical_scroll_top())
        }

        fn paragraphs(count: usize) -> String {
            (0..count)
                .map(|ix| format!("paragraph {ix}"))
                .collect::<Vec<_>>()
                .join("\n\n")
        }

        fn words(count: usize) -> String {
            (0..count)
                .map(|ix| format!("w{ix}"))
                .collect::<Vec<_>>()
                .join(" ")
        }

        #[gpui::test]
        fn a_scrollable_view_scrolls_to_an_offscreen_block(cx: &mut TestAppContext) {
            let (state, cx) = window(&paragraphs(200), Container::Scrollable, cx);
            reveal(&state, "paragraph 150", cx);
            assert!(!is_pending(&state, cx));
            let top = scroll_top(&state, cx);
            assert!((140..=150).contains(&top.item_ix), "{top:?}");

            reveal(&state, "paragraph 3", cx);
            assert!(!is_pending(&state, cx));
            assert!(scroll_top(&state, cx).item_ix <= 3);
        }

        #[gpui::test]
        fn an_append_adding_blocks_keeps_the_scroll_position(cx: &mut TestAppContext) {
            let (state, cx) = window(&paragraphs(200), Container::Scrollable, cx);
            reveal(&state, "paragraph 100", cx);
            let top = scroll_top(&state, cx);
            assert!(top.item_ix > 0, "{top:?}");

            state.update(cx, |state, cx| state.push_str("\n\nparagraph 200", cx));
            cx.run_until_parked();
            draw(cx);

            state.read_with(cx, |state, _| {
                assert_eq!(state.list_state.item_count(), 201);
            });
            assert_unmoved(&state, top, cx);
        }

        #[gpui::test]
        fn a_scrollable_view_scrolls_to_a_line_inside_a_long_paragraph(cx: &mut TestAppContext) {
            let (state, cx) = window(&words(400), Container::Scrollable, cx);
            reveal(&state, "w390", cx);
            assert!(!is_pending(&state, cx));
            let top = scroll_top(&state, cx);
            assert_eq!(top.item_ix, 0);
            assert!(top.offset_in_item > px(100.), "{top:?}");
        }

        #[gpui::test]
        fn revealing_a_visible_line_does_not_scroll(cx: &mut TestAppContext) {
            let (state, cx) = window(&words(400), Container::Scrollable, cx);
            reveal(&state, "w200", cx);
            let top = scroll_top(&state, cx);
            assert!(top.offset_in_item > px(0.), "{top:?}");
            for word in ["w199", "w198", "w197", "w196"] {
                reveal(&state, word, cx);
                assert!(!is_pending(&state, cx));
                let now = scroll_top(&state, cx);
                assert_eq!(
                    (now.item_ix, now.offset_in_item),
                    (top.item_ix, top.offset_in_item),
                    "{word}"
                );
            }
        }

        #[gpui::test]
        fn an_enclosing_list_scrolls_to_a_line_of_a_fit_content_view(cx: &mut TestAppContext) {
            let outer = ListState::new(2, ListAlignment::Top, px(1000.));
            let (state, cx) = window(&words(400), Container::List(outer.clone()), cx);
            reveal(&state, "w390", cx);
            assert!(!is_pending(&state, cx));
            let top = outer.logical_scroll_top();
            assert_eq!(top.item_ix, 1, "{top:?}");
            assert!(top.offset_in_item > px(100.), "{top:?}");
        }

        #[gpui::test]
        fn on_reveal_scrolls_a_container_that_ignores_scroll_requests(cx: &mut TestAppContext) {
            let handle = ScrollHandle::new();
            let (state, cx) = window(&words(400), Container::Div(handle.clone()), cx);
            reveal(&state, "w390", cx);
            assert!(!is_pending(&state, cx));
            assert!(handle.offset().y < px(-100.), "{:?}", handle.offset());
        }

        #[gpui::test]
        fn a_reveal_that_cannot_be_shown_gives_up(cx: &mut TestAppContext) {
            let (state, cx) = window(&words(4000), Container::Fixed, cx);
            reveal(&state, "w3990", cx);
            assert!(is_pending(&state, cx));
            for _ in 0..10 {
                draw(cx);
            }
            assert!(!is_pending(&state, cx));
        }

        #[gpui::test]
        fn a_reveal_not_carried_out_in_time_is_dropped(cx: &mut TestAppContext) {
            let (state, cx) = window(&paragraphs(200), Container::Scrollable, cx);
            request(&state, "paragraph 150", cx, |_, cx| {
                cx.background_executor()
                    .advance_clock(std::time::Duration::from_secs(2))
            });
            draw(cx);
            assert!(!is_pending(&state, cx));
            assert_eq!(scroll_top(&state, cx).item_ix, 0);
        }

        #[gpui::test]
        fn an_empty_range_reveals_its_line(cx: &mut TestAppContext) {
            let (state, cx) = window(&words(400), Container::Scrollable, cx);
            reveal(&state, "w390", cx);
            let top = scroll_top(&state, cx);
            // A position on a visible line leaves the view where it is.
            state.update(cx, |state, cx| {
                let text = state.rendered_text();
                let start = text.as_str().find("w391").unwrap();
                state.reveal_range(start..start, cx).unwrap();
            });
            for _ in 0..3 {
                draw(cx);
            }
            assert!(!is_pending(&state, cx));
            let now = scroll_top(&state, cx);
            assert_eq!(
                (now.item_ix, now.offset_in_item),
                (top.item_ix, top.offset_in_item)
            );
        }

        #[gpui::test]
        fn a_position_after_the_last_character_reveals_its_line(cx: &mut TestAppContext) {
            let (state, cx) = window(&words(400), Container::Scrollable, cx);
            reveal(&state, "w399", cx);
            let top = scroll_top(&state, cx);
            assert!(top.offset_in_item > px(1000.), "{top:?}");
            // The end of the text, on the visible last line.
            state.update(cx, |state, cx| {
                let text = state.rendered_text();
                let end = text.as_str().find("w399").unwrap() + "w399".len();
                state.reveal_range(end..end, cx).unwrap();
            });
            for _ in 0..3 {
                draw(cx);
            }
            assert!(!is_pending(&state, cx));
            let now = scroll_top(&state, cx);
            assert_eq!(
                (now.item_ix, now.offset_in_item),
                (top.item_ix, top.offset_in_item)
            );
        }

        /// Reveals `range` of the current text and draws a few frames.
        fn reveal_at(
            state: &Entity<TextViewState>,
            range: impl FnOnce(&str) -> std::ops::Range<usize>,
            cx: &mut VisualTestContext,
        ) {
            state.update(cx, |state, cx| {
                let text = state.rendered_text();
                let range = range(text.as_str());
                state.reveal_range(range, cx).unwrap();
            });
            for _ in 0..3 {
                draw(cx);
            }
        }

        fn assert_unmoved(
            state: &Entity<TextViewState>,
            top: gpui::ListOffset,
            cx: &mut VisualTestContext,
        ) {
            assert!(!is_pending(state, cx));
            let now = scroll_top(state, cx);
            assert_eq!(
                (now.item_ix, now.offset_in_item),
                (top.item_ix, top.offset_in_item)
            );
        }

        #[gpui::test]
        fn the_end_of_the_text_and_its_separators_reveal_the_last_line(cx: &mut TestAppContext) {
            let (state, cx) = window(&words(400), Container::Scrollable, cx);
            reveal(&state, "w399", cx);
            let top = scroll_top(&state, cx);
            assert!(top.offset_in_item > px(1000.), "{top:?}");
            // The end of the text, after the separator that ends the block.
            reveal_at(&state, |text| text.len()..text.len(), cx);
            assert_unmoved(&state, top, cx);
            // Only that separator.
            reveal_at(&state, |text| text.len() - 1..text.len(), cx);
            assert_unmoved(&state, top, cx);

            let code = (0..200)
                .map(|ix| format!("line {ix}"))
                .collect::<Vec<_>>()
                .join("\n");
            state.update(cx, |state, cx| {
                state.set_text(&format!("```\n{code}\n```"), cx)
            });
            cx.run_until_parked();
            reveal(&state, "line 199", cx);
            let top = scroll_top(&state, cx);
            assert!(top.offset_in_item > px(1000.), "{top:?}");
            reveal_at(&state, |text| text.len()..text.len(), cx);
            assert_unmoved(&state, top, cx);
        }

        #[gpui::test]
        fn the_end_of_a_block_above_reveals_its_last_line(cx: &mut TestAppContext) {
            let second = (0..400)
                .map(|ix| format!("v{ix}"))
                .collect::<Vec<_>>()
                .join(" ");
            let markdown = format!("{}\n\n{second}", words(400));
            let (state, cx) = window(&markdown, Container::Scrollable, cx);
            reveal(&state, "v399", cx);
            assert_eq!(scroll_top(&state, cx).item_ix, 1);
            // The end of the first paragraph, on the separator after it.
            reveal_at(
                &state,
                |text| {
                    let end = text.find("w399").unwrap() + "w399".len();
                    end..end
                },
                cx,
            );
            assert!(!is_pending(&state, cx));
            let top = scroll_top(&state, cx);
            assert_eq!(top.item_ix, 0, "{top:?}");
            assert!(top.offset_in_item > px(1000.), "{top:?}");
        }

        #[gpui::test]
        fn an_empty_view_has_nothing_to_reveal(cx: &mut TestAppContext) {
            cx.update(crate::init);
            let state = cx.update(|cx| cx.new(|cx| TextViewState::markdown("", cx)));
            cx.run_until_parked();
            state.update(cx, |state, cx| {
                assert_eq!(state.reveal_range(0..0, cx), Ok(()));
                assert!(state.pending_reveal.is_none());
            });
        }

        #[gpui::test]
        fn revealing_a_visible_block_does_not_scroll(cx: &mut TestAppContext) {
            let markdown = format!("{}\n\n<div>html</div>\n\n{}", words(400), words(400));
            let (state, cx) = window(&markdown, Container::Scrollable, cx);
            reveal(&state, "html", cx);
            // Still in view a little further down.
            state.update(cx, |state, _| state.list_state.scroll_by(px(30.)));
            draw(cx);
            let top = scroll_top(&state, cx);
            reveal(&state, "html", cx);
            assert_unmoved(&state, top, cx);
        }

        #[gpui::test]
        fn a_line_of_an_inline_flow_counts_as_shown_once_scrolled_to(cx: &mut TestAppContext) {
            // Inline code every tenth word, so the rows are taller than the
            // body line and land between pixels.
            let markdown = (0..400)
                .map(|ix| {
                    if ix % 10 == 0 {
                        format!("`c{ix}`")
                    } else {
                        format!("w{ix}")
                    }
                })
                .collect::<Vec<_>>()
                .join(" ");
            let (state, cx) = window(&markdown, Container::Scrollable, cx);
            reveal(&state, "c390", cx);
            assert!(!is_pending(&state, cx));
            assert!(scroll_top(&state, cx).offset_in_item > px(1000.));
        }

        #[gpui::test]
        fn a_range_starting_on_a_line_break_reveals_the_next_line(cx: &mut TestAppContext) {
            let code = (0..200)
                .map(|ix| format!("line {ix}"))
                .collect::<Vec<_>>()
                .join("\n");
            let (state, cx) = window(&format!("```\n{code}\n```"), Container::Scrollable, cx);
            reveal(&state, "\nline 190", cx);
            assert!(!is_pending(&state, cx));
            let top = scroll_top(&state, cx);
            assert!(top.offset_in_item > px(1000.), "{top:?}");
        }

        #[gpui::test]
        fn a_range_starting_on_a_line_break_in_an_inline_flow_reveals_the_next_line(
            cx: &mut TestAppContext,
        ) {
            // Inline code lays the paragraph out as an inline flow.
            let lines = (0..200)
                .map(|ix| format!("line {ix} `code`"))
                .collect::<Vec<_>>()
                .join("\\\n");
            let (state, cx) = window(&lines, Container::Scrollable, cx);
            reveal(&state, "\nline 190", cx);
            assert!(!is_pending(&state, cx));
            let top = scroll_top(&state, cx);
            assert!(top.offset_in_item > px(1000.), "{top:?}");
        }

        #[gpui::test]
        fn a_reveal_is_dropped_when_its_text_before_it_changes(cx: &mut TestAppContext) {
            let (state, cx) = window(&paragraphs(200), Container::Scrollable, cx);
            let target = "first words then the target";
            let markdown = format!("{target}\n\n{}", paragraphs(200));
            state.update(cx, |state, cx| state.set_text(&markdown, cx));
            cx.run_until_parked();

            // Appending to its paragraph keeps it.
            request(&state, "target", cx, |state, cx| {
                state.set_text(&markdown.replacen("target", "target and more", 1), cx);
                assert!(state.pending_reveal.is_some());
            });
            // An edit before it in its paragraph drops it.
            request(&state, "target", cx, |state, cx| {
                state.set_text(&markdown.replacen("words", "WORDS", 1), cx);
                assert!(state.pending_reveal.is_none());
            });
        }

        #[gpui::test]
        fn a_clamped_view_does_not_reveal(cx: &mut TestAppContext) {
            let outer = ListState::new(2, ListAlignment::Top, px(1000.));
            let (state, cx) = window(&words(400), Container::Clamped(outer.clone()), cx);
            reveal(&state, "w390", cx);
            assert!(!is_pending(&state, cx));
            assert_eq!(outer.logical_scroll_top().item_ix, 0);
        }

        #[gpui::test]
        fn text_outside_every_block_reveals_its_block(cx: &mut TestAppContext) {
            let markdown = format!("{}\n\n<div>html text</div>", paragraphs(100));
            let (state, cx) = window(&markdown, Container::Scrollable, cx);
            reveal(&state, "html text", cx);
            assert!(!is_pending(&state, cx));
            assert!(
                scroll_top(&state, cx).item_ix >= 90,
                "{:?}",
                scroll_top(&state, cx)
            );
        }

        #[gpui::test]
        fn a_reveal_follows_its_text_past_an_edit_before_it(cx: &mut TestAppContext) {
            let (state, cx) = window(&paragraphs(200), Container::Scrollable, cx);
            // An inserted paragraph moves the target down one block.
            request(&state, "paragraph 150", cx, |state, cx| {
                state.set_text(&format!("inserted\n\n{}", paragraphs(200)), cx);
                assert!(state.pending_reveal.is_some());
            });
            for _ in 0..3 {
                draw(cx);
            }
            assert!(!is_pending(&state, cx));
            let top = scroll_top(&state, cx);
            assert!((141..=151).contains(&top.item_ix), "{top:?}");

            // A reveal whose text changed is dropped.
            request(&state, "paragraph 150", cx, |state, cx| {
                state.set_text(&paragraphs(200).replace("paragraph 150", "changed"), cx);
                assert!(state.pending_reveal.is_none());
            });
        }

        #[gpui::test]
        fn malformed_ranges_and_html_views_are_rejected(cx: &mut TestAppContext) {
            cx.update(crate::init);
            let state = cx.update(|cx| cx.new(|cx| TextViewState::markdown("first\n\nsecond", cx)));
            cx.run_until_parked();
            state.update(cx, |state, cx| {
                assert_eq!(
                    state.reveal_range(std::ops::Range { start: 5, end: 3 }, cx),
                    Err(RangeHighlightError::InvalidRange(0))
                );
                assert_eq!(
                    state.reveal_range(0..100, cx),
                    Err(RangeHighlightError::InvalidRange(0))
                );
                state.reveal_range(0..5, cx).unwrap();
            });

            let html = cx.update(|cx| cx.new(|cx| TextViewState::html("<p>one</p>", cx)));
            cx.run_until_parked();
            html.update(cx, |html, cx| {
                assert_eq!(
                    html.reveal_range(0..3, cx),
                    Err(RangeHighlightError::Unsupported)
                );
            });
        }
    }
}
