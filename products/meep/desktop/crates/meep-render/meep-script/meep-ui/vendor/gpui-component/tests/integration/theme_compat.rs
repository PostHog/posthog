use gpui_component::theme::{ThemeConfig, ThemeConfigColors, ThemeMode};

#[test]
fn legacy_text_view_style_struct_literal_shape_is_unchanged() {
    use gpui_component::text::TextViewStyle;

    let defaults = TextViewStyle::default();
    let _ = TextViewStyle {
        paragraph_gap: defaults.paragraph_gap,
        heading_base_font_size: defaults.heading_base_font_size,
        heading_font_size: defaults.heading_font_size,
        highlight_theme: defaults.highlight_theme,
        code_block: defaults.code_block,
        table: defaults.table,
        table_head: defaults.table_head,
        table_cell: defaults.table_cell,
        inline_code: defaults.inline_code,
        is_dark: defaults.is_dark,
    };
}

#[test]
fn theme_config_is_built_from_default() {
    // `ThemeConfig` is `#[non_exhaustive]`, so callers outside the crate
    // start from `Default` and assign the fields they set.
    let mut config = ThemeConfig::default();
    config.name = "Compatibility".into();
    config.mode = ThemeMode::Light;
    config.colors = ThemeConfigColors::default();

    assert_eq!(config.name.as_ref(), "Compatibility");
    assert_eq!(config.mode, ThemeMode::Light);
    assert!(config.highlight.is_none());
}
