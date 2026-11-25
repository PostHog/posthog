//! Compatibility facade for rich text now owned by `gpui-base`.

mod compat;
mod frontmatter;
mod style;

pub use compat::{
    Text, TextView, TextViewLayoutState, TextViewPlugin, TextViewPrepaintState, html, markdown,
};
pub use frontmatter::FrontmatterPlugin;
pub use gpui_base::text::{
    InlineElement, InlineRenderContext, MarkdownBlockParserFn, MarkdownBlockRenderFn,
    MarkdownExtensions, MarkdownNode, MarkdownParseContext, MarkdownPlugin, RangeHighlight,
    RangeHighlightError, RenderedText, SelectionFormat, TableData, TextViewMotion, TextViewState,
    markdown_ast,
};
pub use style::TextViewStyle;

#[cfg(any(feature = "tree-sitter", feature = "syntect"))]
use std::cell::RefCell;
#[cfg(feature = "tree-sitter")]
use std::collections::HashMap;

use gpui::Styled as _;
#[cfg(feature = "tree-sitter")]
use gpui_base::input::{InputEdit, Point, RopeExt as _};
#[cfg(feature = "tree-sitter")]
use ropey::Rope;

#[cfg(feature = "tree-sitter")]
use crate::highlighter::{LanguageRegistry, SyntaxHighlighter};

#[cfg(test)]
mod window_selection;

/// Derives the Base rich-text style installed by the component theme adapter.
pub(crate) fn base_text_view_style(theme: &crate::Theme) -> gpui_base::TextViewStyle {
    let radius = theme.semantic_tokens().radius.md;
    let mut table = gpui::StyleRefinement::default();
    table.corner_radii.top_left = Some(radius.into());
    table.corner_radii.top_right = Some(radius.into());
    table.corner_radii.bottom_left = Some(radius.into());
    table.corner_radii.bottom_right = Some(radius.into());
    let mut code_block = gpui::StyleRefinement::default();
    code_block.corner_radii = table.corner_radii.clone();
    let table_head = gpui::StyleRefinement::default()
        .bg(theme.table_head)
        .text_color(theme.table_head_foreground);

    gpui_base::TextViewStyle::default()
        .with_foreground(theme.foreground)
        .with_muted_foreground(theme.muted_foreground)
        .with_link(theme.link)
        .with_selection(theme.selection)
        .with_code_background(theme.muted)
        .with_border(theme.border)
        .with_code_block(code_block)
        .with_table(table)
        .with_table_head(table_head)
        .with_inline_code(gpui::HighlightStyle {
            background_color: Some(theme.accent),
            ..Default::default()
        })
        .with_dark(theme.is_dark())
}

pub(crate) fn install_text_view_defaults(theme: &crate::Theme, cx: &mut gpui::App) {
    // Component's Root sets the theme foreground, so every container that
    // sets its own text color is one a text view should follow.
    let defaults = gpui_base::TextViewDefaults::new()
        .with_style(base_text_view_style(theme))
        .with_inherit_text_color(true);

    #[cfg(any(feature = "tree-sitter", feature = "syntect"))]
    let defaults = defaults.with_code_block_highlighter(component_code_block_highlighter(
        theme.highlight_theme.clone(),
    ));

    defaults.install(cx);
}

#[cfg(feature = "tree-sitter")]
pub(crate) fn component_code_block_highlighter(
    highlight_theme: std::sync::Arc<crate::highlighter::HighlightTheme>,
) -> impl Fn(&gpui_base::text::CodeBlock) -> Vec<(std::ops::Range<usize>, gpui::HighlightStyle)>
+ Send
+ Sync
+ 'static {
    move |block| {
        thread_local! {
            static HIGHLIGHTERS: RefCell<HashMap<gpui::SharedString, SyntaxHighlighter>> =
                RefCell::new(HashMap::new());
        }

        let Some(lang) = block.lang() else {
            return Vec::new();
        };
        let code = block.code();
        HIGHLIGHTERS.with(|cache| {
            let mut cache = cache.borrow_mut();
            let highlighter = cache
                .entry(lang.clone())
                .or_insert_with(|| SyntaxHighlighter::new(lang.as_ref()));
            if let Some(config) = LanguageRegistry::singleton().language(lang.as_ref())
                && highlighter.language() != &config.name
            {
                *highlighter = SyntaxHighlighter::new(lang.as_ref());
            }

            let old_end_byte = highlighter.text().len();
            let old_end_position = highlighter.text().offset_to_point(old_end_byte);
            let code_rope = Rope::from_str(code.as_ref());
            let edit = InputEdit {
                start_byte: 0,
                old_end_byte,
                new_end_byte: code.len(),
                start_position: Point::new(0, 0),
                old_end_position,
                new_end_position: code_rope.offset_to_point(code.len()),
            };
            highlighter.update_input(Some(edit), &code_rope, None);
            highlighter.styles(&(0..code.len()), highlight_theme.as_ref())
        })
    }
}

/// The syntect counterpart: syntect keeps no state between calls, and the
/// highlights of an unchanged block are cached by the text view itself.
#[cfg(all(feature = "syntect", not(feature = "tree-sitter")))]
pub(crate) fn component_code_block_highlighter(
    highlight_theme: std::sync::Arc<crate::highlighter::HighlightTheme>,
) -> impl Fn(&gpui_base::text::CodeBlock) -> Vec<(std::ops::Range<usize>, gpui::HighlightStyle)>
+ Send
+ Sync
+ 'static {
    move |block| match block.lang() {
        Some(lang) => crate::highlighter::highlight_code(
            lang.as_ref(),
            block.code().as_ref(),
            highlight_theme.as_ref(),
        ),
        None => Vec::new(),
    }
}

/// The type [`shared_code_block_highlighter`] returns.
#[cfg(any(feature = "tree-sitter", feature = "syntect"))]
pub(crate) type SharedCodeBlockHighlighter = dyn Fn(&gpui_base::text::CodeBlock) -> Vec<(std::ops::Range<usize>, gpui::HighlightStyle)>
    + Send
    + Sync;

/// The [`component_code_block_highlighter`] for `highlight_theme`, built once
/// and handed out again for the same theme.
///
/// A code block reuses its highlights only while the highlighter is the same
/// `Arc`, and a text view with a custom theme is laid out every frame, so a
/// fresh highlighter per frame reparsed every code block with tree-sitter on
/// every frame. Each entry keeps its theme alive, so only the most recent few
/// themes are kept.
///
/// Entries are also keyed on the [`LanguageRegistry`] generation: registering
/// a language drops them, so the next frame gets a new highlighter and code
/// blocks painted before the language existed are highlighted again.
#[cfg(any(feature = "tree-sitter", feature = "syntect"))]
pub(crate) fn shared_code_block_highlighter(
    highlight_theme: &std::sync::Arc<crate::highlighter::HighlightTheme>,
) -> std::sync::Arc<SharedCodeBlockHighlighter> {
    // Syntect's languages are fixed at build time, so its entries never go stale.
    #[cfg(feature = "tree-sitter")]
    let generation = LanguageRegistry::singleton().generation();
    #[cfg(not(feature = "tree-sitter"))]
    let generation = 0;
    shared_code_block_highlighter_at(highlight_theme, generation)
}

/// [`shared_code_block_highlighter`] at an explicit registry `generation`.
#[cfg(any(feature = "tree-sitter", feature = "syntect"))]
fn shared_code_block_highlighter_at(
    highlight_theme: &std::sync::Arc<crate::highlighter::HighlightTheme>,
    generation: u64,
) -> std::sync::Arc<SharedCodeBlockHighlighter> {
    use std::sync::Arc;

    use crate::highlighter::HighlightTheme;

    /// The registry generation the entries were built at, and the entries.
    type SharedHighlighters = (
        u64,
        Vec<(Arc<HighlightTheme>, Arc<SharedCodeBlockHighlighter>)>,
    );

    const CAPACITY: usize = 4;
    thread_local! {
        static SHARED: RefCell<SharedHighlighters> = const { RefCell::new((0, Vec::new())) };
    }

    SHARED.with(|cache| {
        let (cached_generation, shared) = &mut *cache.borrow_mut();
        if *cached_generation != generation {
            *cached_generation = generation;
            shared.clear();
        }
        if let Some((_, highlighter)) = shared
            .iter()
            .find(|(theme, _)| Arc::ptr_eq(theme, highlight_theme))
        {
            return highlighter.clone();
        }

        let highlighter: Arc<SharedCodeBlockHighlighter> =
            Arc::new(component_code_block_highlighter(highlight_theme.clone()));
        if shared.len() == CAPACITY {
            shared.remove(0);
        }
        shared.push((highlight_theme.clone(), highlighter.clone()));
        highlighter
    })
}

#[cfg(test)]
mod tests {
    use std::sync::Arc;

    use gpui::{StyleRefinement, Styled as _, px};

    use crate::Theme;

    /// The component highlighter is the only place that still knows about
    /// `LanguageRegistry` and `HighlightTheme`, so these two cases follow it
    /// here from the code block it used to live in.
    /// A Markdown code fence in a language tree-sitter is not built with —
    /// TOML here — is highlighted by syntect in a build that chose it.
    #[cfg(all(feature = "syntect", not(feature = "tree-sitter")))]
    #[test]
    fn syntect_highlights_a_code_fence() {
        use gpui_base::text::CodeBlock;

        use crate::highlighter::HighlightTheme;

        let code = "[package]\nname = \"demo\"\n";
        let highlighter = super::component_code_block_highlighter(HighlightTheme::default_light());
        let styles = highlighter(&CodeBlock::from_code(code, Some("toml")));
        let string = code.find("\"demo\"").unwrap();
        assert!(
            styles
                .iter()
                .any(|(range, style)| range.contains(&string) && style.color.is_some()),
            "the string must be colored: {styles:?}"
        );
        assert_eq!(
            styles.last().map(|(range, _)| range.end),
            Some(code.len()),
            "the runs cover the whole block"
        );
        assert!(highlighter(&CodeBlock::from_code(code, Some("no-such-language"))).is_empty());
    }

    #[cfg(feature = "tree-sitter")]
    mod code_block_highlighter {
        use std::ops::Range;

        use gpui::{HighlightStyle, Hsla, SharedString};
        use gpui_base::text::CodeBlock;

        use crate::highlighter::{HighlightTheme, LanguageConfig, LanguageRegistry};

        fn register_json(lang: &SharedString) {
            LanguageRegistry::singleton().register(
                lang.as_ref(),
                &LanguageConfig::new(
                    lang.clone(),
                    tree_sitter_json::LANGUAGE.into(),
                    vec![],
                    "(number) @number",
                    "",
                    "",
                ),
            );
        }

        fn color_at(
            styles: &[(Range<usize>, HighlightStyle)],
            range: Range<usize>,
        ) -> Option<Hsla> {
            styles
                .iter()
                .find(|(span, _)| span.start <= range.start && span.end >= range.end)
                .and_then(|(_, style)| style.color)
        }

        #[test]
        fn registering_a_language_refreshes_the_cached_highlighter() {
            let lang = SharedString::from("json-cache-test");
            let code = SharedString::from(r#"{"value": 42}"#);
            let number = code.find("42").unwrap()..code.find("42").unwrap() + 2;
            let highlighter =
                super::super::component_code_block_highlighter(HighlightTheme::default_light());

            // The first call caches a plain-text highlighter for the unknown
            // language; the cache must not outlive the registration.
            let block = CodeBlock::from_code(code.clone(), Some(lang.clone()));
            assert_eq!(color_at(&highlighter(&block), number.clone()), None);

            register_json(&lang);

            let block = CodeBlock::from_code(code, Some(lang));
            assert!(
                color_at(&highlighter(&block), number).is_some(),
                "a newly registered language must reach the cached highlighter"
            );
        }

        #[test]
        fn styles_follow_the_highlight_theme_they_were_built_with() {
            let lang = SharedString::from("json-theme-test");
            register_json(&lang);
            let code = SharedString::from(r#"{"value": 42}"#);
            let number = code.find("42").unwrap()..code.find("42").unwrap() + 2;

            let light = HighlightTheme::default_light();
            let dark = HighlightTheme::default_dark();
            let light_number = light.style("number").and_then(|style| style.color);
            let dark_number = dark.style("number").and_then(|style| style.color);
            assert_ne!(
                light_number, dark_number,
                "the default themes must use different number colors"
            );

            let block = CodeBlock::from_code(code, Some(lang));
            let light_styles = super::super::component_code_block_highlighter(light)(&block);
            let dark_styles = super::super::component_code_block_highlighter(dark)(&block);

            assert_eq!(color_at(&light_styles, number.clone()), light_number);
            assert_eq!(
                color_at(&dark_styles, number),
                dark_number,
                "a theme change must not reuse syntax styles from the previous theme"
            );
        }

        #[test]
        fn shared_highlighter_is_reused_for_the_same_theme() {
            // An explicit generation, so registrations by tests running in
            // parallel cannot drop the entries between calls.
            const GENERATION: u64 = u64::MAX;
            let light = HighlightTheme::default_light();
            let dark = HighlightTheme::default_dark();

            let first = super::super::shared_code_block_highlighter_at(&light, GENERATION);
            let again = super::super::shared_code_block_highlighter_at(&light, GENERATION);
            let other = super::super::shared_code_block_highlighter_at(&dark, GENERATION);

            // Code blocks keep their highlights only while the highlighter is
            // the same `Arc`.
            assert!(std::sync::Arc::ptr_eq(&first, &again));
            assert!(!std::sync::Arc::ptr_eq(&first, &other));
        }

        #[test]
        fn registering_a_language_replaces_the_shared_highlighter() {
            let light = HighlightTheme::default_light();

            let before = super::super::shared_code_block_highlighter_at(&light, u64::MAX - 1);
            let after = super::super::shared_code_block_highlighter_at(&light, u64::MAX - 2);

            // A new `Arc` makes code blocks painted before the registration
            // highlight again.
            assert!(!std::sync::Arc::ptr_eq(&before, &after));
        }
    }

    #[test]
    fn component_theme_adapter_maps_text_colors_without_highlighting() {
        let theme = Theme::default();
        let style = super::base_text_view_style(&theme);

        assert_eq!(style.foreground(), theme.foreground);
        assert_eq!(style.muted_foreground(), theme.muted_foreground);
        assert_eq!(style.link(), theme.link);
        assert_eq!(style.selection(), theme.selection);
        assert_eq!(style.inline_code().background_color, Some(theme.accent));
        let radius = theme.semantic_tokens().radius.md;
        assert_eq!(style.table().corner_radii.top_left, Some(radius.into()));
        assert_eq!(style.table().corner_radii.top_right, Some(radius.into()));
        assert_eq!(style.table().corner_radii.bottom_left, Some(radius.into()));
        assert_eq!(style.table().corner_radii.bottom_right, Some(radius.into()));
    }

    #[test]
    fn component_text_view_table_respects_square_base_radius_token() {
        let mut theme = Theme::default();
        theme.radius = gpui::px(0.);

        let style = super::base_text_view_style(&theme);
        let square = Some(gpui::px(0.).into());
        assert_eq!(style.table().corner_radii.top_left, square);
        assert_eq!(style.table().corner_radii.top_right, square);
        assert_eq!(style.table().corner_radii.bottom_left, square);
        assert_eq!(style.table().corner_radii.bottom_right, square);
    }

    #[cfg(feature = "tree-sitter")]
    #[gpui::test]
    fn component_initialization_installs_default_code_highlighting(cx: &mut gpui::TestAppContext) {
        cx.update(crate::init);

        cx.update(|cx| {
            assert!(gpui_base::TextViewDefaults::global(cx).has_code_block_highlighter());
        });
    }

    #[test]
    fn test_text_view_builder() {
        let mut style = super::TextViewStyle::default();
        style.highlight_theme = crate::highlighter::HighlightTheme::default_dark();

        let _: super::TextView = super::markdown("# compatible")
            .style(style)
            .selectable(true)
            .scrollable(true)
            .image_source(|uri| gpui::ImageSource::from(std::path::PathBuf::from(uri.as_ref())));
    }

    #[test]
    fn legacy_text_view_keeps_element_associated_types() {
        fn assert_element_types<T>()
        where
            T: gpui::Element<
                    RequestLayoutState = super::TextViewLayoutState,
                    PrepaintState = super::TextViewPrepaintState,
                >,
        {
        }

        assert_element_types::<super::TextView>();
    }

    #[test]
    fn legacy_default_style_keeps_active_component_theme_colors() {
        let mut theme = Theme::default();
        theme.foreground = gpui::rgb(0xf4f4f5).into();
        theme.link = gpui::rgb(0x38bdf8).into();
        theme.selection = gpui::rgba(0x2563eb66).into();

        let style = super::compat::resolve_component_style(&theme, super::TextViewStyle::default());

        assert_eq!(style.foreground(), theme.foreground);
        assert_eq!(style.link(), theme.link);
        assert_eq!(style.selection(), theme.selection);
    }

    #[test]
    fn legacy_table_refinement_keeps_component_radius() {
        let theme = Theme::default();
        let mut table = gpui::StyleRefinement::default();
        table.overflow.x = Some(gpui::Overflow::Scroll);

        let style = super::compat::resolve_component_style(
            &theme,
            super::TextViewStyle::default().table(table),
        );

        let radius = Some(theme.semantic_tokens().radius.md.into());
        assert_eq!(style.table().corner_radii.top_left, radius);
        assert_eq!(style.table().corner_radii.top_right, radius);
        assert_eq!(style.table().corner_radii.bottom_left, radius);
        assert_eq!(style.table().corner_radii.bottom_right, radius);
        assert_eq!(style.table().overflow.x, Some(gpui::Overflow::Scroll));
    }

    #[test]
    fn legacy_partial_styles_refine_component_theme_defaults() {
        let theme = Theme::default();
        let mut table_head = gpui::StyleRefinement::default();
        table_head.text.font_weight = Some(gpui::FontWeight::BOLD);
        let inline_code = gpui::HighlightStyle {
            font_style: Some(gpui::FontStyle::Italic),
            ..Default::default()
        };

        let style = super::compat::resolve_component_style(
            &theme,
            super::TextViewStyle::default()
                .table_head(table_head)
                .inline_code(inline_code),
        );

        assert_eq!(style.table_head().background, Some(theme.table_head.into()));
        assert_eq!(
            style.table_head().text.color,
            Some(theme.table_head_foreground)
        );
        assert_eq!(
            style.table_head().text.font_weight,
            Some(gpui::FontWeight::BOLD)
        );
        assert_eq!(style.inline_code().background_color, Some(theme.accent));
        assert_eq!(
            style.inline_code().font_style,
            Some(gpui::FontStyle::Italic)
        );
    }

    #[test]
    fn legacy_heading_configuration_maps_to_base_heading_refinements() {
        let theme = Theme::default();
        let mut legacy = super::TextViewStyle::default();
        legacy.heading_base_font_size = px(10.);
        legacy.heading_font_size = Some(Arc::new(|level, base| base * level as f32));

        let style = super::compat::resolve_component_style(&theme, legacy);

        assert_eq!(
            style.heading(2),
            StyleRefinement::default().text_size(px(20.))
        );
    }
}
