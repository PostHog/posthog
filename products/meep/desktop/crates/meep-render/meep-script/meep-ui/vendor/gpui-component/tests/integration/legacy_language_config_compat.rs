// These imports and grammar struct literals were valid in 0.6.0.

use gpui_component::{highlighter::*, input::*};

#[test]
fn grammar_config_remains_unambiguous_with_legacy_glob_imports() {
    let config = LanguageConfig {
        name: "custom".into(),
        #[cfg(feature = "tree-sitter")]
        language: None,
        #[cfg(feature = "tree-sitter")]
        injection_languages: vec![],
        #[cfg(feature = "tree-sitter")]
        highlights: "".into(),
        #[cfg(feature = "tree-sitter")]
        injections: "".into(),
        #[cfg(feature = "tree-sitter")]
        locals: "".into(),
    };
    let LanguageConfig { name, .. } = config;
    assert_eq!(name, "custom");
    let _: Option<EditorState> = None;
    let _ = language_config::LanguageConfig::default();
}

#[test]
fn base_imports_do_not_shadow_legacy_grammar_config() {
    use gpui_base::input::*;
    use gpui_component::highlighter::*;
    let _: Option<LanguageConfig> = None;
    let _: Option<EditorState> = None;
    let _ = language_config::LanguageConfig::default();
}
