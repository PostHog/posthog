use std::{
    cell::RefCell,
    collections::{HashMap, HashSet},
    ops::Range,
    rc::Rc,
    sync::Arc,
};

use gpui::{
    App, AppContext as _, Context, ElementId, EventEmitter, FocusHandle, Focusable, HighlightStyle,
    ListAlignment, ListOffset, ListState, Pixels, ScrollHandle, SharedString, Size, Subscription,
    Task, Window, WindowId, point, px,
};
use gpui_base::{TextSelection, TextSelectionContentKey, TextSelectionEvent, TextSelectionHandle};

use super::{
    DiffAnnotation, DiffConflictResolution, DiffFile, DiffFileStatus, DiffInlineUnit,
    DiffLinePosition, DiffLineRange, DiffMode, DiffSide,
    conflict::ConflictPart,
    presentation::{
        DiffSyntaxHighlighter, FilePresentation, PresentationOptions, SyntaxHighlighters,
    },
    selection::SelectionGeometry,
};

/// One virtualized row. Every row belongs to exactly one file.
#[derive(Clone, Debug, PartialEq, Eq)]
pub(crate) enum DisplayRow {
    /// The file header, with any file-level annotations.
    File(usize),
    /// Binary, metadata-only or empty file summary, for a file without source rows.
    Notice(usize),
    Hunk {
        file: usize,
        hunk: usize,
    },
    Fold {
        file: usize,
        pairs: Range<usize>,
    },
    /// The heading of one part of a merge conflict; for a resolved conflict,
    /// the [`ConflictPart::Current`] heading stands for the whole conflict.
    Conflict {
        file: usize,
        conflict: usize,
        part: ConflictPart,
    },
    Code {
        file: usize,
        original: Option<usize>,
        modified: Option<usize>,
        changed: bool,
    },
}

impl DisplayRow {
    pub(crate) fn file(&self) -> usize {
        match self {
            Self::File(file) | Self::Notice(file) => *file,
            Self::Hunk { file, .. }
            | Self::Fold { file, .. }
            | Self::Conflict { file, .. }
            | Self::Code { file, .. } => *file,
        }
    }
}

/// Which part of a collapsed unchanged range a disclosure reveals.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub(crate) enum FoldExpansion {
    /// The lines just above the following source.
    Up,
    /// The lines just below the preceding source.
    Down,
    All,
}

/// Notifications from the readonly comparison surface.
#[derive(Clone, Debug)]
#[non_exhaustive]
pub enum DiffEvent {
    /// A pointer gesture began selecting source lines from a line number.
    SelectionStarted(DiffLineRange),
    /// A pointer, gutter or keyboard operation changed the selected source lines.
    SelectionChanged(Option<DiffLineRange>),
    /// A selection gesture finished; the range is ready to act on.
    SelectionEnded(DiffLineRange),
    /// The user expanded a collapsed file from its header.
    FileExpanded(SharedString),
    /// The user collapsed a file from its header.
    FileCollapsed(SharedString),
    /// The user resolved a merge conflict, or undid its resolution; read it
    /// with [`DiffState::conflict_resolution`].
    ConflictResolved(SharedString, usize),
}

/// Inputs that determine row heights and content width.
#[derive(Clone, Debug, PartialEq)]
pub(crate) struct LayoutKey {
    rem: Pixels,
    font_size: Pixels,
    font_family: SharedString,
    mode: DiffMode,
    line_number: bool,
    marker_lane: bool,
    soft_wrap: bool,
}

impl LayoutKey {
    pub(crate) fn new(
        rem: Pixels,
        font_size: Pixels,
        font_family: SharedString,
        mode: DiffMode,
        line_number: bool,
        marker_lane: bool,
        soft_wrap: bool,
    ) -> Self {
        Self {
            rem,
            font_size,
            font_family,
            mode,
            line_number,
            marker_lane,
            soft_wrap,
        }
    }
}

/// The row showing each source line, or the disclosure hiding it.
#[derive(Default)]
struct FileRows {
    original: Vec<Option<usize>>,
    modified: Vec<Option<usize>>,
}

/// The selected source lines of one file, resolved for membership tests.
#[derive(Clone, Debug, PartialEq, Eq)]
pub(crate) enum SelectedLines {
    /// Lines numbered `lines` on one side.
    Side {
        file: usize,
        side: DiffSide,
        lines: Range<usize>,
    },
    /// Patch lines in `patch` order, across both sides.
    Patch { file: usize, patch: Range<usize> },
}

impl SelectedLines {
    pub(crate) fn contains(
        &self,
        files: &[DiffFile],
        file: usize,
        side: DiffSide,
        ix: usize,
    ) -> bool {
        match self {
            Self::Side {
                file: selected,
                side: selected_side,
                lines,
            } => {
                *selected == file
                    && *selected_side == side
                    && lines.contains(&files[file].line_number(side, ix))
            }
            Self::Patch {
                file: selected,
                patch,
            } => *selected == file && patch.contains(&files[file].patch_ix(side, ix)),
        }
    }

    /// The last selected line, where a selection's add-annotation button sits.
    pub(crate) fn is_last(
        &self,
        files: &[DiffFile],
        file: usize,
        side: DiffSide,
        ix: usize,
    ) -> bool {
        match self {
            Self::Side {
                file: selected,
                side: selected_side,
                lines,
            } => {
                *selected == file
                    && *selected_side == side
                    && files[file].line_number(side, ix) + 1 == lines.end
            }
            Self::Patch {
                file: selected,
                patch,
            } => *selected == file && files[file].patch_ix(side, ix) + 1 == patch.end,
        }
    }
}

/// Retained focus, viewport, context expansion and selection for a
/// [`super::Diff`] showing one or more files of a patch.
///
/// Create once in the owning view. Mutations notify observers; the application
/// owns the patch and chooses when to install new files. Syntax and inline
/// emphasis are prepared on a background thread and appear once ready.
pub struct DiffState {
    files: Vec<DiffFile>,
    /// Each path's index in `files`; the first file wins a duplicated path.
    file_ixs: HashMap<SharedString, usize>,
    mode: DiffMode,
    context_lines: Option<usize>,
    expansion_lines: usize,
    min_collapsed_lines: usize,
    expanded: Vec<Vec<Range<usize>>>,
    collapsed: HashSet<SharedString>,
    resolutions: HashMap<(SharedString, usize), DiffConflictResolution>,
    file_rows: Vec<FileRows>,
    header_rows: Vec<usize>,
    rows: Rc<Vec<DisplayRow>>,
    change_rows: Vec<usize>,
    list: ListState,
    horizontal_scroll: ScrollHandle,
    focus: FocusHandle,
    selection: TextSelectionHandle,
    geometry: Rc<RefCell<SelectionGeometry>>,
    selected_lines: Option<DiffLineRange>,
    selection_anchor: Option<DiffLinePosition>,
    selection_cursor: Option<DiffLinePosition>,
    selecting: bool,
    presentation_options: PresentationOptions,
    syntax_highlighter: Option<DiffSyntaxHighlighter>,
    presentations: Vec<Option<Arc<FilePresentation>>>,
    viewport: Size<Pixels>,
    layout: Option<LayoutKey>,
    content_width: Pixels,
    row_height: Option<Pixels>,
    /// The list width the row-height hint was last applied at.
    hinted_width: Option<Pixels>,
    annotations: HashSet<(Option<DiffLinePosition>, SharedString, ElementId)>,
    window: Option<WindowId>,
    /// Bumped when files or presentation options change, so a preparation
    /// started for earlier ones never installs its results.
    presentation_generation: usize,
    preparing: Option<usize>,
    _presentation: Task<()>,
    _selection_subscription: Subscription,
}

impl EventEmitter<DiffEvent> for DiffState {}
impl Focusable for DiffState {
    fn focus_handle(&self, _: &App) -> FocusHandle {
        self.focus.clone()
    }
}

impl DiffState {
    /// Creates a unified viewer with three unchanged lines around each change.
    pub fn new(files: impl IntoIterator<Item = DiffFile>, cx: &mut Context<Self>) -> Self {
        let focus = cx.focus_handle().tab_stop(true);
        let selection = TextSelectionHandle::new("", cx);
        let geometry = Rc::new(RefCell::new(SelectionGeometry::default()));
        let weak = cx.entity().downgrade();
        selection.resolve_content_key_with(
            {
                let weak = weak.clone();
                let geometry = geometry.clone();
                move |point, cx| {
                    let state = weak.upgrade()?;
                    let snapshot = state.read(cx).selection.snapshot(cx);
                    let entity = Some(state.read(cx).selection.entity_id());
                    let snapshot =
                        snapshot.filter(|snapshot| snapshot.anchor().entity_id() == entity);
                    let side = snapshot
                        .and_then(|snapshot| snapshot.anchor().content_key())
                        .map(|key| decode_key(key.value()).1);
                    geometry
                        .borrow()
                        .key_at(point, side)
                        .map(TextSelectionContentKey::new)
                        .or_else(|| {
                            snapshot
                                .filter(|snapshot| snapshot.cursor().entity_id() == entity)
                                .and_then(|snapshot| snapshot.cursor().content_key())
                        })
                }
            },
            cx,
        );
        selection.copy_with(
            {
                let weak = weak.clone();
                move |cx| {
                    weak.upgrade()
                        .map_or_else(String::new, |state| state.read(cx).selected_text(cx))
                }
            },
            cx,
        );
        selection.focus_with(
            {
                let focus = focus.clone();
                move |window, cx| window.focus(&focus, cx)
            },
            cx,
        );
        let _selection_subscription = selection.subscribe(
            move |event, cx| {
                let _ = weak.update(cx, |state, cx| {
                    if !state.selection.has_local_selection(cx) {
                        match event {
                            TextSelectionEvent::SelectionChanged(Some(_)) => {
                                let changed = state.selected_lines.take().is_some();
                                // A new text gesture ends the previous gutter anchor.
                                state.selection_anchor = None;
                                state.selection_cursor = None;
                                if changed {
                                    cx.emit(DiffEvent::SelectionChanged(None));
                                }
                            }
                            TextSelectionEvent::Cleared => {
                                // A replacement gutter gesture has local selection and
                                // skips this branch. Keep its anchor for Shift-click,
                                // but report a clear that leaves no replacement range.
                                if state.selected_lines.take().is_some() {
                                    cx.emit(DiffEvent::SelectionChanged(None));
                                }
                            }
                            _ => {}
                        }
                    }
                    cx.notify();
                });
            },
            cx,
        );
        let files = files.into_iter().collect::<Vec<_>>();
        let mut state = Self {
            expanded: vec![Vec::new(); files.len()],
            presentations: vec![None; files.len()],
            file_ixs: file_ixs(&files),
            files,
            mode: DiffMode::Unified,
            context_lines: Some(3),
            expansion_lines: 20,
            min_collapsed_lines: 2,
            collapsed: HashSet::new(),
            resolutions: HashMap::new(),
            file_rows: Vec::new(),
            header_rows: Vec::new(),
            rows: Rc::default(),
            change_rows: Vec::new(),
            list: ListState::new(0, ListAlignment::Top, px(0.)),
            horizontal_scroll: ScrollHandle::new(),
            focus,
            selection,
            geometry,
            selected_lines: None,
            selection_anchor: None,
            selection_cursor: None,
            selecting: false,
            presentation_options: PresentationOptions {
                inline_unit: Some(DiffInlineUnit::Word),
                inline_max_line_length: 1000,
                syntax_max_line_length: 1000,
            },
            syntax_highlighter: None,
            viewport: Size::default(),
            layout: None,
            content_width: px(0.),
            row_height: None,
            hinted_width: None,
            annotations: HashSet::new(),
            window: None,
            presentation_generation: 0,
            preparing: None,
            _presentation: Task::ready(()),
            _selection_subscription,
        };
        state.rebuild(true);
        state
    }

    /// Sets the initial display mode. Default is [`DiffMode::Unified`].
    pub fn with_mode(mut self, mode: DiffMode) -> Self {
        self.mode = mode;
        self.rebuild(true);
        self
    }

    /// Sets the initial unchanged context around each change. Default is
    /// `Some(3)`; `None` shows every supplied patch line.
    pub fn with_context_lines(mut self, lines: Option<usize>) -> Self {
        self.context_lines = lines;
        self.rebuild(true);
        self
    }

    /// Sets how many lines an up or down disclosure reveals. Default is 20.
    pub fn with_expansion_lines(mut self, lines: usize) -> Self {
        self.expansion_lines = lines.max(1);
        self
    }

    /// Sets the shortest unchanged range that collapses; shorter ranges stay
    /// visible. Default is 2.
    pub fn with_min_collapsed_lines(mut self, lines: usize) -> Self {
        self.min_collapsed_lines = lines.max(1);
        self.rebuild(true);
        self
    }

    /// Sets the unit inline changes between paired lines are emphasized in,
    /// or `None` to emphasize whole lines only. Default is [`DiffInlineUnit::Word`].
    pub fn with_inline_unit(mut self, unit: Option<DiffInlineUnit>) -> Self {
        self.presentation_options.inline_unit = unit;
        self.reset_presentation();
        self
    }

    /// Sets the longest line, in bytes, compared for inline changes. Default is 1,000.
    pub fn with_inline_max_line_length(mut self, length: usize) -> Self {
        self.presentation_options.inline_max_line_length = length;
        self.reset_presentation();
        self
    }

    /// Sets the longest line, in bytes, given syntax emphasis. Default is 1,000.
    pub fn with_syntax_max_line_length(mut self, length: usize) -> Self {
        self.presentation_options.syntax_max_line_length = length;
        self.reset_presentation();
        self
    }

    /// Highlights syntax with the application's highlighter instead of GPUI
    /// Kit's. Given a file's [language](DiffFile::language) and the source
    /// text of one side of one hunk, it returns byte ranges into that text
    /// with their styles; a range that splits a character is ignored.
    ///
    /// It runs on the background executor, once for each side of each hunk,
    /// so an unterminated comment in one hunk cannot color the next. Styles
    /// are kept as returned rather than resolved against the theme when a line
    /// paints; set a new highlighter when its colors change.
    pub fn with_syntax_highlighter<F>(mut self, highlighter: F) -> Self
    where
        F: Fn(&str, &str) -> Vec<(Range<usize>, HighlightStyle)> + Send + Sync + 'static,
    {
        self.syntax_highlighter = Some(Arc::new(highlighter));
        self.reset_presentation();
        self
    }

    /// Replaces the application's highlighter, preparing syntax again without
    /// resetting selection or scrolling. See [`Self::with_syntax_highlighter`].
    pub fn set_syntax_highlighter<F>(&mut self, highlighter: F, cx: &mut Context<Self>)
    where
        F: Fn(&str, &str) -> Vec<(Range<usize>, HighlightStyle)> + Send + Sync + 'static,
    {
        self.replace_syntax_highlighter(Some(Arc::new(highlighter)), cx);
    }

    /// Returns to GPUI Kit's highlighter, preparing syntax again without
    /// resetting selection or scrolling.
    pub fn clear_syntax_highlighter(&mut self, cx: &mut Context<Self>) {
        self.replace_syntax_highlighter(None, cx);
    }

    fn replace_syntax_highlighter(
        &mut self,
        highlighter: Option<DiffSyntaxHighlighter>,
        cx: &mut Context<Self>,
    ) {
        self.syntax_highlighter = highlighter;
        self.reset_presentation();
        self.ensure_presentation(cx);
        cx.notify();
    }

    /// Changes the number of lines each disclosure reveals, preserving selection and scrolling.
    pub fn set_expansion_lines(&mut self, lines: usize, cx: &mut Context<Self>) {
        let lines = lines.max(1);
        if self.expansion_lines == lines {
            return;
        }
        self.expansion_lines = lines;
        cx.notify();
    }

    /// Changes the shortest unchanged range that collapses, preserving selection and scrolling.
    pub fn set_min_collapsed_lines(&mut self, lines: usize, cx: &mut Context<Self>) {
        let lines = lines.max(1);
        if self.min_collapsed_lines == lines {
            return;
        }
        self.min_collapsed_lines = lines;
        self.rebuild_at_anchor();
        cx.notify();
    }

    /// Changes the inline comparison unit without resetting selection or scrolling.
    pub fn set_inline_unit(&mut self, unit: Option<DiffInlineUnit>, cx: &mut Context<Self>) {
        if self.presentation_options.inline_unit == unit {
            return;
        }
        self.presentation_options.inline_unit = unit;
        self.reset_presentation();
        self.ensure_presentation(cx);
        cx.notify();
    }

    /// Changes the inline comparison line limit in bytes without resetting selection or scrolling.
    pub fn set_inline_max_line_length(&mut self, length: usize, cx: &mut Context<Self>) {
        if self.presentation_options.inline_max_line_length == length {
            return;
        }
        self.presentation_options.inline_max_line_length = length;
        self.reset_presentation();
        self.ensure_presentation(cx);
        cx.notify();
    }

    /// Changes the syntax emphasis line limit in bytes without resetting selection or scrolling.
    pub fn set_syntax_max_line_length(&mut self, length: usize, cx: &mut Context<Self>) {
        if self.presentation_options.syntax_max_line_length == length {
            return;
        }
        self.presentation_options.syntax_max_line_length = length;
        self.reset_presentation();
        self.ensure_presentation(cx);
        cx.notify();
    }

    /// The files in patch order.
    pub fn files(&self) -> &[DiffFile] {
        &self.files
    }
    pub fn mode(&self) -> DiffMode {
        self.mode
    }
    pub fn context_lines(&self) -> Option<usize> {
        self.context_lines
    }
    pub fn expansion_lines(&self) -> usize {
        self.expansion_lines
    }
    pub fn min_collapsed_lines(&self) -> usize {
        self.min_collapsed_lines
    }
    pub fn inline_unit(&self) -> Option<DiffInlineUnit> {
        self.presentation_options.inline_unit
    }
    pub fn inline_max_line_length(&self) -> usize {
        self.presentation_options.inline_max_line_length
    }
    pub fn syntax_max_line_length(&self) -> usize {
        self.presentation_options.syntax_max_line_length
    }
    pub fn selected_lines(&self) -> Option<DiffLineRange> {
        self.selected_lines.clone()
    }
    /// Whether the file at `path` shows only its header.
    pub fn is_file_collapsed(&self, path: &str) -> bool {
        self.collapsed.contains(path)
    }

    pub(crate) fn rows(&self) -> &Rc<Vec<DisplayRow>> {
        &self.rows
    }
    pub(crate) fn list(&self) -> &ListState {
        &self.list
    }
    pub(crate) fn horizontal_scroll(&self) -> &ScrollHandle {
        &self.horizontal_scroll
    }
    pub(crate) fn selection(&self) -> &TextSelectionHandle {
        &self.selection
    }
    pub(crate) fn geometry(&self) -> &Rc<RefCell<SelectionGeometry>> {
        &self.geometry
    }
    pub(crate) fn presentations(&self) -> &[Option<Arc<FilePresentation>>] {
        &self.presentations
    }
    /// The body's size as of the last paint.
    pub(crate) fn viewport(&self) -> Size<Pixels> {
        self.viewport
    }
    /// The width rows need to show their longest line.
    pub(crate) fn content_width(&self) -> Pixels {
        self.content_width
    }
    pub(crate) fn set_content_width(&mut self, width: Pixels) {
        self.content_width = width;
    }
    /// Records the painted body size and widest painted row. Returns whether
    /// either changed, so the frame must be laid out again.
    pub(crate) fn record_paint(&mut self, viewport: Size<Pixels>, painted_width: Pixels) -> bool {
        let wider = painted_width > self.content_width;
        if wider {
            self.content_width = painted_width;
        }
        let resized = self.viewport != viewport;
        self.viewport = viewport;
        wider || resized
    }

    /// Replaces the files and resets expansion, selection and viewport.
    /// Collapsed files stay collapsed when their path is still present.
    pub fn set_files(&mut self, files: impl IntoIterator<Item = DiffFile>, cx: &mut Context<Self>) {
        if let Some(window) = self.window
            && self.selection_is_local(cx)
        {
            TextSelection::clear_for_window(window, cx);
        }
        self.files = files.into_iter().collect();
        self.file_ixs = file_ixs(&self.files);
        self.collapsed
            .retain(|path| self.file_ixs.contains_key(path));
        self.resolutions.clear();
        self.expanded = vec![Vec::new(); self.files.len()];
        self.reset_presentation();
        self.layout = None;
        self.annotations.clear();
        self.selection.set_local_selection(false, cx);
        self.selection.set_fallback_copy_text("", cx);
        self.selected_lines = None;
        self.selection_anchor = None;
        self.selection_cursor = None;
        self.selecting = false;
        self.geometry.borrow_mut().clear();
        self.rebuild(true);
        self.horizontal_scroll.set_offset(point(px(0.), px(0.)));
        self.ensure_presentation(cx);
        cx.notify();
    }

    /// Changes the display mode while preserving source-line selection and a
    /// nearby source row.
    pub fn set_mode(&mut self, mode: DiffMode, cx: &mut Context<Self>) {
        if self.mode == mode {
            return;
        }
        self.mode = mode;
        self.rebuild_at_anchor();
        self.horizontal_scroll.set_offset(point(px(0.), px(0.)));
        cx.notify();
    }

    /// Sets surrounding context. `None` shows every supplied patch line.
    pub fn set_context_lines(&mut self, lines: Option<usize>, cx: &mut Context<Self>) {
        if self.context_lines == lines {
            return;
        }
        self.context_lines = lines;
        self.expanded.iter_mut().for_each(Vec::clear);
        self.rebuild_at_anchor();
        cx.notify();
    }

    /// Reveals all unchanged source while preserving the configured context count.
    pub fn expand_unchanged(&mut self, cx: &mut Context<Self>) {
        for (expanded, file) in self.expanded.iter_mut().zip(&self.files) {
            *expanded = vec![0..file.pairs().len()];
        }
        self.rebuild_at_anchor();
        cx.notify();
    }

    /// Restores the configured context disclosures.
    pub fn collapse_unchanged(&mut self, cx: &mut Context<Self>) {
        self.expanded.iter_mut().for_each(Vec::clear);
        self.rebuild_at_anchor();
        cx.notify();
    }

    /// Collapses the file at `path` to its header, or expands it, without
    /// emitting a user event.
    pub fn set_file_collapsed(&mut self, path: &str, collapsed: bool, cx: &mut Context<Self>) {
        let Some(file) = self.file_ix(path) else {
            return;
        };
        let path = self.files[file].path().clone();
        let changed = if collapsed {
            self.collapsed.insert(path)
        } else {
            self.collapsed.remove(&path)
        };
        if changed {
            self.rebuild_at_anchor();
            cx.notify();
        }
    }

    /// The resolution of conflict `ix` in the file at `path`, if any.
    /// Use [`DiffFile::conflicts`] to enumerate valid indices; `None` means
    /// unresolved, or that the file or index does not exist.
    pub fn conflict_resolution(&self, path: &str, ix: usize) -> Option<DiffConflictResolution> {
        let file = &self.files[self.file_ix(path)?];
        self.resolutions.get(&(file.path().clone(), ix)).copied()
    }

    /// Resolves conflict `ix` (an index in [`DiffFile::conflicts`]) in the file
    /// at `path`, or clears its resolution
    /// with `None`, without emitting a user event.
    pub fn resolve_conflict(
        &mut self,
        path: &str,
        ix: usize,
        resolution: Option<DiffConflictResolution>,
        cx: &mut Context<Self>,
    ) {
        let Some(file) = self.file_ix(path) else {
            return;
        };
        if ix >= self.files[file].conflicts().len() {
            return;
        }
        let key = (self.files[file].path().clone(), ix);
        let previous = match resolution {
            Some(resolution) => self.resolutions.insert(key, resolution),
            None => self.resolutions.remove(&key),
        };
        if previous != resolution {
            self.rebuild_at_anchor();
            cx.notify();
        }
    }

    /// The working file with every conflict replaced by its resolution, or
    /// `None` while a conflict is unresolved or `path` names no conflicted file.
    pub fn resolved_text(&self, path: &str) -> Option<String> {
        let file = &self.files[self.file_ix(path)?];
        if file.status() != DiffFileStatus::Conflicted {
            return None;
        }
        let lines = file.lines(DiffSide::Modified);
        let source = file.source(DiffSide::Modified);
        let mut text = String::with_capacity(source.len());
        let mut ix = 0;
        for (conflict_ix, conflict) in file.conflicts().iter().enumerate() {
            let resolution = *self.resolutions.get(&(file.path().clone(), conflict_ix))?;
            for line in &lines[ix..conflict.source_lines().start] {
                text.push_str(&source[line.source()]);
            }
            for range in conflict.kept(resolution) {
                for line in &lines[range] {
                    text.push_str(&source[line.source()]);
                }
            }
            ix = conflict.source_lines().end;
        }
        for line in &lines[ix..] {
            text.push_str(&source[line.source()]);
        }
        Some(text)
    }

    /// Synchronizes source-line selection without emitting a user event.
    /// Clips to supplied patch lines; a range containing none clears selection.
    pub fn set_selected_lines(&mut self, range: Option<DiffLineRange>, cx: &mut Context<Self>) {
        let range = range.and_then(|range| self.clip_range(&range));
        if self.selected_lines == range {
            return;
        }
        self.selection_anchor = range.as_ref().map(DiffLineRange::start_position);
        self.selection_cursor = range.as_ref().map(DiffLineRange::end_position);
        self.selection.set_local_selection(range.is_some(), cx);
        self.selected_lines = range;
        cx.notify();
    }

    /// Returns selected source without gutters, diff markers or annotation content.
    pub fn selected_text(&self, cx: &App) -> String {
        if self.selection.has_local_selection(cx)
            && let Some(selected) = self.selected_span()
        {
            return match selected {
                SelectedLines::Side { file, side, lines } => {
                    self.files[file].text_for_lines(side, lines.start, lines.end - 1)
                }
                SelectedLines::Patch { file, patch } => {
                    let file = &self.files[file];
                    let mut text = String::new();
                    for line in &file.patch_lines()[patch] {
                        // An unchanged line reads the same on both sides.
                        let (side, ix) = match line.line(DiffSide::Modified) {
                            Some(ix) => (DiffSide::Modified, ix),
                            None => (
                                DiffSide::Original,
                                line.line(DiffSide::Original).unwrap_or(0),
                            ),
                        };
                        // A side's unterminated final line can precede the
                        // other side's lines in patch order.
                        if !text.is_empty() && !text.ends_with('\n') {
                            text.push('\n');
                        }
                        text.push_str(&file.source(side)[file.lines(side)[ix].source()]);
                    }
                    text
                }
            };
        }
        let Some((file, side, range)) =
            super::selection::selected_source_range(&self.selection, cx)
        else {
            return String::new();
        };
        self.files
            .get(file)
            .and_then(|file| file.source(side).get(range))
            .unwrap_or("")
            .to_owned()
    }

    /// Reveals and scrolls to a source line, expanding its file and hidden
    /// context if needed.
    pub fn scroll_to_line(&mut self, position: DiffLinePosition, cx: &mut Context<Self>) {
        if self.line_index(&position).is_none() {
            return;
        }
        if self.collapsed.remove(position.path().as_str()) {
            self.rebuild_at_anchor();
        }
        if self.expand_line(&position).is_some() {
            self.reveal_line(&position);
            cx.notify();
        }
    }

    /// Scrolls to the header of the file at `path`, a [`DiffFile::path`].
    pub fn scroll_to_file(&mut self, path: &str, cx: &mut Context<Self>) {
        let Some(item_ix) = self
            .file_ix(path)
            .and_then(|file| self.header_rows.get(file).copied())
        else {
            return;
        };
        self.list.scroll_to(ListOffset {
            item_ix,
            offset_in_item: px(0.),
        });
        cx.notify();
    }

    /// Moves to the next changed group after the current viewport, across files,
    /// wrapping to the first once the list is scrolled to its end.
    pub fn next_change(&mut self, cx: &mut Context<Self>) {
        self.move_change(true, cx);
    }
    /// Moves to the previous changed group before the current viewport, across files.
    pub fn previous_change(&mut self, cx: &mut Context<Self>) {
        self.move_change(false, cx);
    }

    /// Reveals part or all of a collapsed unchanged range.
    pub(crate) fn expand_fold(
        &mut self,
        file: usize,
        pairs: Range<usize>,
        expansion: FoldExpansion,
        cx: &mut Context<Self>,
    ) {
        let lines = self.expansion_lines;
        let revealed = match expansion {
            FoldExpansion::All => pairs,
            FoldExpansion::Up => pairs.end.saturating_sub(lines).max(pairs.start)..pairs.end,
            FoldExpansion::Down => pairs.start..(pairs.start + lines).min(pairs.end),
        };
        if let Some(expanded) = self.expanded.get_mut(file) {
            expanded.push(revealed);
            self.rebuild_at_anchor();
            cx.notify();
        }
    }

    /// Resolves a conflict from its heading and reports the user's change.
    pub(crate) fn choose_conflict(
        &mut self,
        file: usize,
        ix: usize,
        resolution: Option<DiffConflictResolution>,
        cx: &mut Context<Self>,
    ) {
        let path = self.files[file].path().clone();
        self.resolve_conflict(&path, ix, resolution, cx);
        cx.emit(DiffEvent::ConflictResolved(path, ix));
    }

    /// Toggles a file from its header and reports the user's change.
    pub(crate) fn toggle_file_collapsed(&mut self, file: usize, cx: &mut Context<Self>) {
        let path = self.files[file].path().clone();
        let collapsed = !self.collapsed.contains(&path);
        self.set_file_collapsed(&path, collapsed, cx);
        cx.emit(if collapsed {
            DiffEvent::FileCollapsed(path)
        } else {
            DiffEvent::FileExpanded(path)
        });
    }

    /// Starts a line-number selection gesture, extending the current anchor in
    /// the same file when `extend` is set.
    pub(crate) fn begin_line_selection(
        &mut self,
        position: DiffLinePosition,
        extend: bool,
        window: &mut Window,
        cx: &mut Context<Self>,
    ) {
        if self.line_index(&position).is_none() {
            return;
        }
        let anchor = self
            .selection_anchor
            .clone()
            .filter(|anchor| extend && self.can_extend(anchor, &position))
            .unwrap_or_else(|| position.clone());
        TextSelection::clear(window, cx);
        window.focus(&self.focus, cx);
        self.selecting = true;
        cx.emit(DiffEvent::SelectionStarted(range_between(
            &anchor, &position,
        )));
        self.select_user_range(anchor, position, cx);
    }

    /// Extends an active line-number gesture to `position` in the same file.
    pub(crate) fn drag_line_selection(
        &mut self,
        position: DiffLinePosition,
        cx: &mut Context<Self>,
    ) {
        let Some(anchor) = self.selection_anchor.clone() else {
            return;
        };
        if !self.selecting
            || !self.can_extend(&anchor, &position)
            || self.selection_cursor.as_ref() == Some(&position)
            || self.line_index(&position).is_none()
        {
            return;
        }
        self.select_user_range(anchor, position, cx);
    }

    /// Whether a selection anchored at `anchor` may extend to `position`:
    /// within one file, and across sides only in Unified mode, whose rows
    /// follow patch order.
    fn can_extend(&self, anchor: &DiffLinePosition, position: &DiffLinePosition) -> bool {
        anchor.path() == position.path()
            && (anchor.side() == position.side() || self.mode == DiffMode::Unified)
    }

    /// Finishes an active line-number gesture.
    pub(crate) fn end_line_selection(&mut self, cx: &mut Context<Self>) {
        if !std::mem::take(&mut self.selecting) {
            return;
        }
        if let Some(range) = self.selected_lines.clone() {
            cx.emit(DiffEvent::SelectionEnded(range));
        }
    }

    /// Selects one line, or extends to it, as a complete gesture.
    #[cfg(test)]
    pub(crate) fn click_line(
        &mut self,
        position: DiffLinePosition,
        extend: bool,
        window: &mut Window,
        cx: &mut Context<Self>,
    ) {
        self.begin_line_selection(position, extend, window, cx);
        self.end_line_selection(cx);
    }

    pub(crate) fn keyboard_select(
        &mut self,
        direction: isize,
        extend: bool,
        window: &mut Window,
        cx: &mut Context<Self>,
    ) {
        let Some((file, side)) = self.active_side(cx) else {
            return;
        };
        let count = self.files[file].lines_count(side);
        let ix = self
            .selection_cursor
            .as_ref()
            .filter(|position| {
                position.side() == side && self.file_ix(position.path()) == Some(file)
            })
            .and_then(|position| self.line_index(position))
            .map(|ix| ix.saturating_add_signed(direction).min(count - 1))
            .unwrap_or(0);
        let position = self.position(file, side, ix);
        let anchor = self
            .selection_anchor
            .clone()
            .filter(|anchor| extend && anchor.path() == position.path())
            .unwrap_or_else(|| position.clone());
        TextSelection::clear(window, cx);
        window.focus(&self.focus, cx);
        let range = self.select_user_range(anchor, position.clone(), cx);
        cx.emit(DiffEvent::SelectionEnded(range));
        if let Some(row) = self.expand_line(&position) {
            self.list.scroll_to_reveal_item(row);
        }
    }

    pub(crate) fn select_all(&mut self, window: &mut Window, cx: &mut Context<Self>) {
        let Some((file, side)) = self.active_side(cx) else {
            return;
        };
        let count = self.files[file].lines_count(side);
        TextSelection::clear(window, cx);
        window.focus(&self.focus, cx);
        let range = self.select_user_range(
            self.position(file, side, 0),
            self.position(file, side, count - 1),
            cx,
        );
        cx.emit(DiffEvent::SelectionEnded(range));
    }

    /// The selected lines, resolved for membership tests.
    pub(crate) fn selected_span(&self) -> Option<SelectedLines> {
        let range = self.selected_lines.as_ref()?;
        let file = self.file_ix(range.path())?;
        if range.is_single_side() {
            let (start, end) = (
                range.start().min(range.end()),
                range.start().max(range.end()),
            );
            return Some(SelectedLines::Side {
                file,
                side: range.side(),
                lines: start..end + 1,
            });
        }
        let document = &self.files[file];
        let start = document.patch_ix(
            range.side(),
            document.line_index(range.side(), range.start())?,
        );
        let end = document.patch_ix(
            range.end_side(),
            document.line_index(range.end_side(), range.end())?,
        );
        Some(SelectedLines::Patch {
            file,
            patch: start.min(end)..start.max(end) + 1,
        })
    }

    /// Records the window that renders this state, for clearing its text selection.
    pub(crate) fn set_window(&mut self, window: WindowId) {
        self.window = Some(window);
    }

    /// Updates width and row-height measurement when fonts or layout change.
    /// Returns whether content width must be measured again.
    pub(crate) fn update_layout(&mut self, key: LayoutKey, row_height: Pixels) -> bool {
        if self.layout.as_ref() == Some(&key) {
            return false;
        }
        if self.layout.is_some() {
            self.list.remeasure();
        }
        self.layout = Some(key);
        self.row_height = Some(row_height);
        self.apply_row_height_hint();
        true
    }

    /// Re-measures rows whose annotations were added, removed or replaced.
    /// Visible rows are re-measured every frame, so content changes inside an
    /// annotation need no notification.
    pub(crate) fn sync_annotations(&mut self, annotations: &[DiffAnnotation]) {
        let current = annotations
            .iter()
            .map(|annotation| {
                (
                    annotation.position().cloned(),
                    annotation.path().clone(),
                    annotation.id().clone(),
                )
            })
            .collect::<HashSet<_>>();
        if current == self.annotations {
            return;
        }
        let rows = current
            .symmetric_difference(&self.annotations)
            .filter_map(|(position, path, _)| match position {
                Some(position) => self.source_row(position),
                None => self
                    .file_ix(path)
                    .and_then(|file| self.header_rows.get(file).copied()),
            })
            .collect::<Vec<_>>();
        for row in rows {
            self.list.remeasure_items(row..row + 1);
        }
        self.annotations = current;
    }

    pub(crate) fn position(&self, file: usize, side: DiffSide, ix: usize) -> DiffLinePosition {
        let document = &self.files[file];
        DiffLinePosition::new(
            document.path().clone(),
            side,
            document.line_number(side, ix),
        )
    }

    fn file_ix(&self, path: &str) -> Option<usize> {
        self.file_ixs.get(path).copied()
    }

    fn line_index(&self, position: &DiffLinePosition) -> Option<usize> {
        self.files[self.file_ix(position.path())?].line_index(position.side(), position.line())
    }

    /// Clips a range to supplied lines, normalizing a single-side range.
    fn clip_range(&self, range: &DiffLineRange) -> Option<DiffLineRange> {
        let file = &self.files[self.file_ix(range.path())?];
        let first_at_or_after = |side: DiffSide, line: usize| {
            let lines = file.lines(side);
            lines
                .get(lines.partition_point(|source| source.line_number() < line))
                .map(|source| source.line_number())
        };
        let last_at_or_before = |side: DiffSide, line: usize| {
            let lines = file.lines(side);
            lines
                .partition_point(|source| source.line_number() <= line)
                .checked_sub(1)
                .map(|ix| lines[ix].line_number())
        };
        if range.is_single_side() {
            let (start, end) = (
                range.start().min(range.end()),
                range.start().max(range.end()),
            );
            let start = first_at_or_after(range.side(), start)?;
            let end = last_at_or_before(range.side(), end)?;
            return (start <= end)
                .then(|| DiffLineRange::new(range.path().clone(), range.side(), start, end));
        }
        let start = first_at_or_after(range.side(), range.start())
            .or_else(|| last_at_or_before(range.side(), range.start()))?;
        let end = last_at_or_before(range.end_side(), range.end())
            .or_else(|| first_at_or_after(range.end_side(), range.end()))?;
        Some(
            DiffLineRange::new(range.path().clone(), range.side(), start, end)
                .with_end_side(range.end_side()),
        )
    }

    fn selection_is_local(&self, cx: &App) -> bool {
        let entity = Some(self.selection.entity_id());
        self.selection
            .snapshot(cx)
            .is_some_and(|snapshot| snapshot.anchor().entity_id() == entity)
    }

    /// The file and side that keyboard selection and Select All act on.
    fn active_side(&self, cx: &App) -> Option<(usize, DiffSide)> {
        let (file, side) = self
            .selection_cursor
            .as_ref()
            .and_then(|cursor| Some((self.file_ix(cursor.path())?, Some(cursor.side()))))
            .filter(|_| self.selected_lines.is_some())
            .or_else(|| {
                super::selection::selected_source_range(&self.selection, cx)
                    .map(|(file, side, _)| (file, Some(side)))
            })
            .or_else(|| {
                let top = self.list.logical_scroll_top().item_ix;
                self.rows.get(top).map(|row| (row.file(), None))
            })?;
        let document = self.files.get(file)?;
        let side = side.unwrap_or(if document.lines_count(DiffSide::Modified) > 0 {
            DiffSide::Modified
        } else {
            DiffSide::Original
        });
        (document.lines_count(side) > 0).then_some((file, side))
    }

    fn expand_line(&mut self, position: &DiffLinePosition) -> Option<usize> {
        let row = self.source_row(position)?;
        if let Some(DisplayRow::Fold { file, pairs }) = self.rows.get(row) {
            let (file, pairs) = (*file, pairs.clone());
            self.expanded[file].push(pairs);
            self.rebuild_at_anchor();
        }
        self.source_row(position)
    }

    /// Selects from `anchor` to `cursor` in one file and reports a change.
    fn select_user_range(
        &mut self,
        anchor: DiffLinePosition,
        cursor: DiffLinePosition,
        cx: &mut Context<Self>,
    ) -> DiffLineRange {
        let range = range_between(&anchor, &cursor);
        let changed = self.selected_lines.as_ref() != Some(&range);
        self.selected_lines = Some(range.clone());
        self.selection_anchor = Some(anchor);
        self.selection_cursor = Some(cursor);
        self.selection.set_local_selection(true, cx);
        if changed {
            cx.emit(DiffEvent::SelectionChanged(Some(range.clone())));
        }
        cx.notify();
        range
    }

    fn move_change(&mut self, forward: bool, cx: &mut Context<Self>) {
        let top = self.list.logical_scroll_top().item_ix;
        let groups = &self.change_rows;
        let target = if forward {
            // Scrolled to the end, the list clamps any later change below the
            // top, so the top never passes it and the key would stop there.
            // The last row's bounds answer even when the rows above the
            // viewport were never measured, as after a jump to the end.
            let at_end = self
                .list
                .item_count()
                .checked_sub(1)
                .and_then(|last| self.list.bounds_for_item(last))
                .is_some_and(|last| last.bottom() <= self.list.viewport_bounds().bottom());
            groups
                .get(groups.partition_point(|ix| *ix <= top))
                .copied()
                .filter(|_| !at_end)
                .or(groups.first().copied())
        } else {
            groups
                .partition_point(|ix| *ix < top)
                .checked_sub(1)
                .and_then(|ix| groups.get(ix))
                .copied()
                .or(groups.last().copied())
        };
        if let Some(ix) = target {
            self.list.scroll_to(ListOffset {
                item_ix: ix,
                offset_in_item: px(0.),
            });
            cx.notify();
        }
    }

    /// The source line shown by a row, looking past headers within its file.
    fn row_position(&self, ix: usize) -> Option<DiffLinePosition> {
        let row = self.rows.get(ix)?;
        let file = row.file();
        let pair_position = |original: Option<usize>, modified: Option<usize>| {
            modified
                .map(|ix| self.position(file, DiffSide::Modified, ix))
                .or_else(|| original.map(|ix| self.position(file, DiffSide::Original, ix)))
        };
        match row {
            DisplayRow::Code {
                original, modified, ..
            } => pair_position(*original, *modified),
            DisplayRow::Fold { pairs, .. } => self.files[file]
                .pairs()
                .get(pairs.start)
                .and_then(|pair| pair_position(pair.original(), pair.modified())),
            DisplayRow::File(_)
            | DisplayRow::Notice(_)
            | DisplayRow::Hunk { .. }
            | DisplayRow::Conflict { .. } => self
                .rows
                .get(ix + 1)
                .filter(|next| next.file() == file)
                .and_then(|_| self.row_position(ix + 1)),
        }
    }

    pub(crate) fn source_row(&self, position: &DiffLinePosition) -> Option<usize> {
        let rows = self.file_rows.get(self.file_ix(position.path())?)?;
        let rows = match position.side() {
            DiffSide::Original => &rows.original,
            DiffSide::Modified => &rows.modified,
        };
        rows.get(self.line_index(position)?).copied().flatten()
    }

    fn reveal_line(&self, position: &DiffLinePosition) {
        if let Some(item_ix) = self.source_row(position) {
            self.list.scroll_to(ListOffset {
                item_ix,
                offset_in_item: px(0.),
            });
        }
    }

    /// Rebuilds rows and restores the source line at the top of the viewport.
    fn rebuild_at_anchor(&mut self) {
        let anchor = self.row_position(self.list.logical_scroll_top().item_ix);
        self.rebuild(false);
        if let Some(anchor) = anchor {
            self.reveal_line(&anchor);
        }
    }

    /// Projects rows. Without `reset`, only the changed middle is spliced so
    /// measured heights of unchanged rows survive disclosure changes.
    fn rebuild(&mut self, reset: bool) {
        let rows = self.project_rows();
        self.file_rows = source_rows(&self.files, &rows);
        self.change_rows = changed_groups(&rows);
        self.header_rows = rows
            .iter()
            .enumerate()
            .filter_map(|(ix, row)| matches!(row, DisplayRow::File(_)).then_some(ix))
            .collect();
        if reset {
            self.list.reset(rows.len());
        } else {
            let old = &self.rows;
            let prefix = old.iter().zip(&rows).take_while(|(a, b)| a == b).count();
            let suffix = old
                .iter()
                .rev()
                .zip(rows.iter().rev())
                .take(old.len().min(rows.len()) - prefix)
                .take_while(|(a, b)| a == b)
                .count();
            self.list
                .splice(prefix..old.len() - suffix, rows.len() - prefix - suffix);
        }
        self.rows = Rc::new(rows);
        self.apply_row_height_hint();
    }

    fn project_rows(&self) -> Vec<DisplayRow> {
        let mut rows = Vec::new();
        for (ix, file) in self.files.iter().enumerate() {
            rows.push(DisplayRow::File(ix));
            if self.collapsed.contains(file.path()) {
                continue;
            }
            if file.pairs().is_empty() {
                rows.push(DisplayRow::Notice(ix));
            } else if file.status() == DiffFileStatus::Unchanged {
                rows.extend((0..file.pairs().len()).map(|line| DisplayRow::Code {
                    file: ix,
                    original: None,
                    modified: Some(line),
                    changed: false,
                }));
            } else if file.status() == DiffFileStatus::Conflicted {
                let resolutions = (0..file.conflicts().len())
                    .map(|conflict| {
                        self.resolutions
                            .get(&(file.path().clone(), conflict))
                            .copied()
                    })
                    .collect::<Vec<_>>();
                let visible = visible_pairs(
                    file,
                    self.context_lines,
                    self.min_collapsed_lines,
                    &self.expanded[ix],
                );
                project_conflicts(&mut rows, ix, file, &visible, &resolutions);
            } else {
                project_file(
                    &mut rows,
                    ix,
                    file,
                    self.mode,
                    self.context_lines,
                    self.min_collapsed_lines,
                    &self.expanded[ix],
                );
            }
        }
        rows
    }

    /// Applies the row-height hint again once the list has laid out at a new
    /// width. Returns whether it did, so the frame must be laid out again.
    ///
    /// A list that lays out at a new width forgets every row height, hints
    /// included, which happens on its first layout too. The patch then
    /// measures only the rows rendered so far, and scrolling stops once the
    /// last of them reaches the bottom of the viewport. Call this after the
    /// list's prepaint, so the hint is back before the next wheel event.
    pub(crate) fn keep_row_height_hint(&mut self) -> bool {
        let width = self.list.viewport_bounds().size.width;
        if self.row_height.is_none() || self.hinted_width == Some(width) {
            return false;
        }
        self.hinted_width = Some(width);
        self.apply_row_height_hint();
        true
    }

    /// Gives unmeasured rows a code-row height so the scrollbar is sized for
    /// the whole patch before every row has been rendered.
    fn apply_row_height_hint(&self) {
        if let Some(height) = self.row_height {
            let _ = self.list.clone().with_uniform_item_height(height);
        }
    }

    /// Discards prepared emphasis after files or options change.
    fn reset_presentation(&mut self) {
        self.presentations = vec![None; self.files.len()];
        self.presentation_generation += 1;
        self.preparing = None;
        self._presentation = Task::ready(());
    }

    /// Prepares syntax and inline emphasis for files that lack it, one file at
    /// a time on the background executor, reusing highlighters per language.
    /// Starts on first render, so builders applied after `new` take effect.
    pub(crate) fn ensure_presentation(&mut self, cx: &mut Context<Self>) {
        let generation = self.presentation_generation;
        if self.preparing == Some(generation) {
            return;
        }
        let pending = self
            .presentations
            .iter()
            .enumerate()
            .filter(|(_, presentation)| presentation.is_none())
            .map(|(ix, _)| (ix, self.files[ix].clone()))
            .collect::<Vec<_>>();
        if pending.is_empty() {
            return;
        }
        let options = self.presentation_options;
        let custom = self.syntax_highlighter.clone();
        self.preparing = Some(generation);
        self._presentation = cx.spawn(async move |this, cx| {
            let mut highlighters = Some(SyntaxHighlighters::default());
            for (ix, file) in pending {
                let mut moved = highlighters.take();
                let custom = custom.clone();
                let (presentation, returned) = cx
                    .background_spawn(async move {
                        let presentation = FilePresentation::prepare(
                            &file,
                            options,
                            moved.get_or_insert_default(),
                            custom.as_ref(),
                        );
                        (presentation, moved)
                    })
                    .await;
                highlighters = returned;
                let current = this.update(cx, |state, cx| {
                    if state.presentation_generation != generation {
                        return false;
                    }
                    if let Some(slot) = state.presentations.get_mut(ix) {
                        *slot = Some(Arc::new(presentation));
                    }
                    cx.notify();
                    true
                });
                if !matches!(current, Ok(true)) {
                    return;
                }
            }
        });
    }
}

/// The range from `anchor` to `cursor`, normalized when both are on one side.
fn range_between(anchor: &DiffLinePosition, cursor: &DiffLinePosition) -> DiffLineRange {
    if anchor.side() == cursor.side() {
        DiffLineRange::new(
            cursor.path().clone(),
            cursor.side(),
            anchor.line().min(cursor.line()),
            anchor.line().max(cursor.line()),
        )
    } else {
        DiffLineRange::new(
            cursor.path().clone(),
            anchor.side(),
            anchor.line(),
            cursor.line(),
        )
        .with_end_side(cursor.side())
    }
}

fn file_ixs(files: &[DiffFile]) -> HashMap<SharedString, usize> {
    let mut ixs = HashMap::with_capacity(files.len());
    for (ix, file) in files.iter().enumerate() {
        ixs.entry(file.path().clone()).or_insert(ix);
    }
    ixs
}

/// Every source line maps to its code row or the disclosure hiding it; lines
/// of a collapsed file have no row. Disjoint folds visit each pair once, so
/// building the maps is linear.
fn source_rows(files: &[DiffFile], rows: &[DisplayRow]) -> Vec<FileRows> {
    let mut file_rows = files
        .iter()
        .map(|file| FileRows {
            original: vec![None; file.lines_count(DiffSide::Original)],
            modified: vec![None; file.lines_count(DiffSide::Modified)],
        })
        .collect::<Vec<_>>();
    for (row_ix, row) in rows.iter().enumerate() {
        let mut map = |file: usize, original: Option<usize>, modified: Option<usize>| {
            if let Some(line) = original {
                file_rows[file].original[line] = Some(row_ix);
            }
            if let Some(line) = modified {
                file_rows[file].modified[line] = Some(row_ix);
            }
        };
        match row {
            DisplayRow::Code {
                file,
                original,
                modified,
                ..
            } => map(*file, *original, *modified),
            DisplayRow::Fold { file, pairs } => {
                for pair in &files[*file].pairs()[pairs.clone()] {
                    map(*file, pair.original(), pair.modified());
                }
            }
            DisplayRow::File(_)
            | DisplayRow::Notice(_)
            | DisplayRow::Hunk { .. }
            | DisplayRow::Conflict { .. } => {}
        }
    }
    file_rows
}

fn changed_groups(rows: &[DisplayRow]) -> Vec<usize> {
    let changed = |row: &DisplayRow| matches!(row, DisplayRow::Code { changed: true, .. });
    rows.iter()
        .enumerate()
        .filter_map(|(ix, row)| {
            (changed(row)
                && (ix == 0 || !changed(&rows[ix - 1]) || rows[ix - 1].file() != row.file()))
            .then_some(ix)
        })
        .collect()
}

const SIDE_BIT: u64 = 1 << 40;
const OFFSET_MASK: u64 = SIDE_BIT - 1;

/// Packs a source offset into a selection key, ordered by file, side and offset.
pub(crate) fn encode_key(file: usize, side: DiffSide, offset: usize) -> u64 {
    ((file as u64) << 41)
        | if side == DiffSide::Modified {
            SIDE_BIT
        } else {
            0
        }
        | (offset as u64 & OFFSET_MASK)
}
pub(crate) fn decode_key(key: u64) -> (usize, DiffSide, usize) {
    (
        (key >> 41) as usize,
        if key & SIDE_BIT == 0 {
            DiffSide::Original
        } else {
            DiffSide::Modified
        },
        (key & OFFSET_MASK) as usize,
    )
}

/// The end of the hunk containing each pair; a fixture without hunks is one.
fn hunk_ends(document: &DiffFile) -> Vec<usize> {
    let pairs = document.pairs();
    let mut hunk_end = vec![pairs.len(); pairs.len()];
    for hunk in document.hunks() {
        hunk_end[hunk.pairs()].fill(hunk.pairs().end);
    }
    hunk_end
}

/// Which pairs show as code: changes with their context, expanded ranges,
/// and collapsed ranges shorter than `min_collapsed_lines`.
fn visible_pairs(
    document: &DiffFile,
    context: Option<usize>,
    min_collapsed_lines: usize,
    expanded: &[Range<usize>],
) -> Vec<bool> {
    let pairs = document.pairs();
    let hunks = document.hunks();
    let mut hunk_end = vec![pairs.len(); pairs.len()];
    let mut hunk_start = vec![0; pairs.len()];
    for hunk in hunks {
        hunk_start[hunk.pairs()].fill(hunk.pairs().start);
        hunk_end[hunk.pairs()].fill(hunk.pairs().end);
    }
    // Interval boundaries avoid repeatedly filling overlapping context windows.
    // Projection remains linear in source lines plus the number of disclosures.
    let mut boundaries = vec![0isize; pairs.len() + 1];
    if let Some(context) = context {
        let mut ix = 0;
        while ix < pairs.len() {
            if !pairs[ix].is_changed() {
                ix += 1;
                continue;
            }
            let start = ix;
            while ix < pairs.len() && ix < hunk_end[start] && pairs[ix].is_changed() {
                ix += 1;
            }
            boundaries[start.saturating_sub(context).max(hunk_start[start])] += 1;
            boundaries[ix.saturating_add(context).min(hunk_end[start])] -= 1;
        }
    } else {
        boundaries[0] += 1;
        boundaries[pairs.len()] -= 1;
    }
    for range in expanded {
        let start = range.start.min(pairs.len());
        let end = range.end.min(pairs.len());
        if start < end {
            boundaries[start] += 1;
            boundaries[end] -= 1;
        }
    }
    let mut active = 0;
    let mut visible = boundaries[..pairs.len()]
        .iter()
        .map(|boundary| {
            active += boundary;
            active > 0
        })
        .collect::<Vec<_>>();
    // A disclosure shorter than the threshold would hide almost nothing.
    let mut ix = 0;
    while ix < pairs.len() {
        if visible[ix] {
            ix += 1;
            continue;
        }
        let start = ix;
        while ix < pairs.len() && ix < hunk_end[start] && !visible[ix] {
            ix += 1;
        }
        if ix - start < min_collapsed_lines {
            visible[start..ix].fill(true);
        }
    }
    visible
}

fn project_file(
    rows: &mut Vec<DisplayRow>,
    file: usize,
    document: &DiffFile,
    mode: DiffMode,
    context: Option<usize>,
    min_collapsed_lines: usize,
    expanded: &[Range<usize>],
) {
    let pairs = document.pairs();
    let hunks = document.hunks();
    let hunk_end = hunk_ends(document);
    let visible = visible_pairs(document, context, min_collapsed_lines, expanded);
    let mut hunk_ix = 0;
    let mut ix = 0;
    while ix < pairs.len() {
        while let Some(hunk) = hunks.get(hunk_ix) {
            if hunk.pairs().start != ix {
                break;
            }
            rows.push(DisplayRow::Hunk {
                file,
                hunk: hunk_ix,
            });
            hunk_ix += 1;
        }
        if !visible[ix] {
            let start = ix;
            while ix < pairs.len() && ix < hunk_end[start] && !visible[ix] {
                ix += 1;
            }
            rows.push(DisplayRow::Fold {
                file,
                pairs: start..ix,
            });
        } else if mode == DiffMode::Unified && pairs[ix].is_changed() {
            let start = ix;
            while ix < pairs.len() && ix < hunk_end[start] && pairs[ix].is_changed() {
                ix += 1;
            }
            for pair in &pairs[start..ix] {
                if let Some(original) = pair.original() {
                    rows.push(DisplayRow::Code {
                        file,
                        original: Some(original),
                        modified: None,
                        changed: true,
                    });
                }
            }
            for pair in &pairs[start..ix] {
                if let Some(modified) = pair.modified() {
                    rows.push(DisplayRow::Code {
                        file,
                        original: None,
                        modified: Some(modified),
                        changed: true,
                    });
                }
            }
        } else {
            let pair = pairs[ix];
            rows.push(DisplayRow::Code {
                file,
                original: pair.original(),
                modified: pair.modified(),
                changed: pair.is_changed(),
            });
            ix += 1;
        }
    }
}

/// Projects a conflicted working file: shared lines fold like context, and
/// each conflict shows its parts, or only the kept lines once resolved.
fn project_conflicts(
    rows: &mut Vec<DisplayRow>,
    file: usize,
    document: &DiffFile,
    visible: &[bool],
    resolutions: &[Option<DiffConflictResolution>],
) {
    // Each line of a conflicted file is its own pair.
    let code = |line: usize, changed: bool| DisplayRow::Code {
        file,
        original: None,
        modified: Some(line),
        changed,
    };
    let conflicts = document.conflicts();
    let mut next = 0;
    let mut ix = 0;
    while ix < visible.len() {
        if let Some(conflict) = conflicts.get(next)
            && conflict.source_lines().start == ix
        {
            match resolutions[next] {
                None => {
                    for part in [
                        ConflictPart::Current,
                        ConflictPart::Base,
                        ConflictPart::Incoming,
                    ] {
                        if let Some(lines) = conflict.part(part) {
                            rows.push(DisplayRow::Conflict {
                                file,
                                conflict: next,
                                part,
                            });
                            rows.extend(lines.map(|line| code(line, true)));
                        }
                    }
                }
                Some(resolution) => {
                    rows.push(DisplayRow::Conflict {
                        file,
                        conflict: next,
                        part: ConflictPart::Current,
                    });
                    for lines in conflict.kept(resolution) {
                        rows.extend(lines.map(|line| code(line, false)));
                    }
                }
            }
            ix = conflict.source_lines().end;
            next += 1;
            continue;
        }
        if visible[ix] {
            rows.push(code(ix, false));
            ix += 1;
            continue;
        }
        let start = ix;
        while ix < visible.len() && !visible[ix] {
            ix += 1;
        }
        rows.push(DisplayRow::Fold {
            file,
            pairs: start..ix,
        });
    }
}
