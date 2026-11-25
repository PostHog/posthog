use gpui::SharedString;

/// Built-in aliases for editing defaults when no exact grammar name is registered.
/// Availability of a parser does not change what a language name means.
pub(crate) fn language_name(name: &str) -> SharedString {
    let name = name.to_lowercase();
    match name.as_str() {
        "plain" => "text".into(),
        "plaintext" => "text".into(),
        "jsonc" => "json".into(),
        "sh" => "bash".into(),
        "c++" => "cpp".into(),
        "cs" => "csharp".into(),
        "scss" => "css".into(),
        "ex" => "elixir".into(),
        "js" => "javascript".into(),
        "kt" => "kotlin".into(),
        "kts" => "kotlin".into(),
        "ktm" => "kotlin".into(),
        "makefile" => "make".into(),
        "md" => "markdown".into(),
        "mdx" => "markdown".into(),
        "markdown-inline" => "markdown_inline".into(),
        "php3" => "php".into(),
        "php4" => "php".into(),
        "php5" => "php".into(),
        "phtml" => "php".into(),
        "protobuf" => "proto".into(),
        "py" => "python".into(),
        "rb" => "ruby".into(),
        "rs" => "rust".into(),
        "ts" => "typescript".into(),
        "yml" => "yaml".into(),
        "pyi" => "python".into(),
        _ => name.into(),
    }
}
