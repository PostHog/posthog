use std::{ops::Range, rc::Rc, sync::Arc};

use gpui::{AnyElement, Context, HighlightStyle, Hsla, SharedString, Window};
use ropey::Rope;

use super::{EditorState, FoldRange, InputEdit};
use crate::SemanticThemeTokens;

/// Resolves semantic highlight names into renderable GPUI styles.
///
/// Base deliberately knows nothing about a concrete syntax theme. UI crates and
/// applications can provide any resolver, independently of their parser.
pub trait HighlightStyleResolver: Send + Sync {
    fn style(&self, name: &str) -> Option<HighlightStyle>;
}

#[derive(Default)]
struct NoHighlightStyles;

impl HighlightStyleResolver for NoHighlightStyles {
    fn style(&self, _: &str) -> Option<HighlightStyle> {
        None
    }
}

/// Parser-independent syntax highlighting seam consumed by the Base editor.
///
/// Implementations own parsing, incremental state, and language-specific
/// behavior. Base only asks for styled ranges and fold candidates.
pub trait InputHighlighter {
    fn language(&self) -> SharedString;

    fn update(
        &mut self,
        edit: Option<InputEdit>,
        text: &Rope,
        folding: bool,
        window: &mut Window,
        cx: &mut Context<EditorState>,
    );

    /// Apply several edits made as one change, such as typing with multiple
    /// cursors. Each entry is an edit with the text as it stood right after
    /// it, in the order the edits were applied.
    ///
    /// The default hands each edit to [`Self::update`] in turn. Override it to
    /// reparse once for the whole change.
    fn update_batch(
        &mut self,
        edits: &[(InputEdit, Rope)],
        folding: bool,
        window: &mut Window,
        cx: &mut Context<EditorState>,
    ) {
        for (edit, text) in edits {
            self.update(Some(*edit), text, folding, window, cx);
        }
    }

    /// Return ordered, non-overlapping style runs that fully cover `range`.
    /// Use [`HighlightStyle::default`] for text without a semantic style.
    fn styles(
        &self,
        range: &Range<usize>,
        resolver: &dyn HighlightStyleResolver,
    ) -> Vec<(Range<usize>, HighlightStyle)>;

    fn fold_ranges(&self, text: &Rope) -> Vec<FoldRange>;

    fn fold_ranges_for_edit(&self, range: Range<usize>, text: &Rope) -> Vec<FoldRange> {
        let _ = range;
        self.fold_ranges(text)
    }
}

pub type InputHighlighterFactory = Rc<dyn Fn(&str) -> Option<Box<dyn InputHighlighter>>>;
pub type SharedHighlightStyleResolver = Arc<dyn HighlightStyleResolver>;
pub type FoldIconRenderer = Rc<dyn Fn(usize, bool) -> AnyElement>;

/// Where in the syntax tree an offset sits, for editing decisions.
///
/// Parser-independent: `gpui-component` answers from tree-sitter, apps may
/// answer heuristically. `None` (no provider installed) means `Code`.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum SyntaxContext {
    Code,
    String,
    Comment,
}

/// Answers syntax context for editing decisions (pairing, skip, indent).
///
/// Created per editor by the application's [`super::LanguageProvider`].
/// Base never imports a parser; implementations live in UI crates or apps.
pub trait SyntaxContextProvider {
    fn context_at(&self, text: &Rope, offset: usize) -> SyntaxContext;
}

#[derive(Clone, Copy, Default)]
pub struct DiagnosticColors {
    pub error: Hsla,
    pub warning: Hsla,
    pub info: Hsla,
    pub hint: Hsla,
}

/// Application-owned colors and highlight resolver consumed by editor painting.
#[derive(Clone)]
pub struct InputEditorStyle {
    pub foreground: Hsla,
    pub muted_foreground: Hsla,
    pub background: Hsla,
    pub border: Hsla,
    pub selection: Hsla,
    pub caret: Hsla,
    pub diagnostics: DiagnosticColors,
    pub highlight_styles: SharedHighlightStyleResolver,
    pub editor_invisible: Option<Hsla>,
    pub editor_active_line: Option<Hsla>,
    pub editor_gutter_background: Option<Hsla>,
    pub fold_icon_renderer: Option<FoldIconRenderer>,
}

impl InputEditorStyle {
    /// Fills in every colour that was left unset, from the active palette.
    ///
    /// `Hsla::default()` is fully transparent, and every colour on `Default` is
    /// that — so an input nothing projected onto painted its glyphs, its caret
    /// and its selection in nothing at all. Transparent is not a colour anyone
    /// means for ink, which is what makes it usable as "unset" here.
    ///
    /// This is resolution, not assignment: whatever a consumer did project is
    /// kept exactly. `crates/component` projects the whole style on every render and
    /// never reaches this; a consumer that projects once at construction gets
    /// the palette that is current now rather than the one that happened to be
    /// installed when the state was built.
    pub fn resolved(&self, tokens: &SemanticThemeTokens) -> Self {
        let colors = &tokens.colors;
        let unset = |value: Hsla| value.a == 0.;
        let or = |value: Hsla, fallback: Hsla| if unset(value) { fallback } else { value };

        let foreground = or(self.foreground, colors.foreground);
        let mut selection = self.selection;
        if unset(selection) {
            selection = colors.accent;
            // A selection must not hide the glyphs it selects.
            selection.a = 0.4;
        }

        Self {
            foreground,
            muted_foreground: or(self.muted_foreground, colors.muted_foreground),
            background: or(self.background, colors.surface),
            border: or(self.border, colors.border),
            selection,
            caret: or(self.caret, foreground),
            ..self.clone()
        }
    }
}

impl Default for InputEditorStyle {
    fn default() -> Self {
        Self {
            foreground: Hsla::default(),
            muted_foreground: Hsla::default(),
            background: Hsla::default(),
            border: Hsla::default(),
            selection: Hsla::default(),
            caret: Hsla::default(),
            diagnostics: DiagnosticColors::default(),
            highlight_styles: Arc::new(NoHighlightStyles),
            editor_invisible: None,
            editor_active_line: None,
            editor_gutter_background: None,
            fold_icon_renderer: None,
        }
    }
}

#[cfg(test)]
mod tests {
    use gpui::hsla;

    use super::InputEditorStyle;
    use crate::SemanticThemeTokens;

    fn dark() -> SemanticThemeTokens {
        let mut tokens = SemanticThemeTokens::default();
        tokens.colors.foreground = hsla(0., 0., 0.98, 1.0);
        tokens.colors.muted_foreground = hsla(0., 0., 0.64, 1.0);
        tokens.colors.surface = hsla(0., 0., 0.04, 1.0);
        tokens.colors.border = hsla(0., 0., 0.15, 1.0);
        tokens.colors.accent = hsla(0.6, 0.5, 0.5, 1.0);
        tokens
    }

    #[test]
    fn an_unprojected_style_takes_its_ink_from_the_palette() {
        let tokens = dark();
        let resolved = InputEditorStyle::default().resolved(&tokens);

        assert_eq!(resolved.foreground, tokens.colors.foreground);
        assert_eq!(resolved.caret, tokens.colors.foreground);
        assert_eq!(resolved.muted_foreground, tokens.colors.muted_foreground);
        assert_eq!(resolved.background, tokens.colors.surface);
        assert_eq!(resolved.border, tokens.colors.border);
        // The point of the change: every one of these was transparent, so an
        // input nothing projected onto painted its text in nothing at all.
        for colour in [
            resolved.foreground,
            resolved.caret,
            resolved.muted_foreground,
            resolved.selection,
        ] {
            assert!(colour.a > 0., "{colour:?} is still invisible");
        }
    }

    #[test]
    fn a_selection_stays_translucent_enough_to_read_through() {
        let resolved = InputEditorStyle::default().resolved(&dark());
        assert_eq!(resolved.selection.a, 0.4);
    }

    #[test]
    fn projected_colours_are_kept_verbatim() {
        let chosen = hsla(0.3, 0.4, 0.5, 1.0);
        let style = InputEditorStyle {
            foreground: chosen,
            caret: chosen,
            ..Default::default()
        };
        let resolved = style.resolved(&dark());

        assert_eq!(resolved.foreground, chosen);
        assert_eq!(resolved.caret, chosen);
        // And what was not projected still comes from the palette.
        assert_eq!(resolved.border, dark().colors.border);
    }

    #[test]
    fn resolution_never_consumes_its_own_output() {
        // The projected style is kept verbatim precisely so that this holds:
        // resolving against a second palette must follow it, not stay on the
        // first. Resolving in place would have frozen after one pass.
        let projected = InputEditorStyle::default();
        let first = projected.resolved(&dark());

        let mut light = SemanticThemeTokens::default();
        light.colors.foreground = hsla(0., 0., 0.04, 1.0);
        let second = projected.resolved(&light);

        assert_ne!(first.foreground, second.foreground);
        assert_eq!(second.foreground, light.colors.foreground);
    }
}
