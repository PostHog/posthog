use anyhow::{Result, bail};
/// The named part of a pattern argument: the whole argument (`{body}`) or
/// what follows its first `=` (`body={body}`, `--body={body}`). Returns the
/// fixed prefix and the name. Anything else in a pattern is fixed text, so
/// a GraphQL query's own braces never read as a name.
pub fn hole(token: &str) -> Option<(&str, &str)> {
    let (prefix, rest) = match token.find('=') {
        Some(i) if !token.starts_with('{') => token.split_at(i + 1),
        _ => ("", token),
    };
    let name = rest.strip_prefix('{')?.strip_suffix('}')?;
    (name.len() <= 32
        && name.starts_with(|c: char| c.is_ascii_lowercase())
        && name
            .chars()
            .all(|c| c.is_ascii_lowercase() || c.is_ascii_digit() || c == '_'))
    .then_some((prefix, name))
}

/// The names a pattern lets change, in order. A pattern is the whole
/// command: it starts with its action, fixes everything else but at least
/// one named part, and has no control characters.
pub fn validate_pattern(action: &[String], pattern: &[String]) -> Result<Vec<String>> {
    if pattern.is_empty()
        || pattern.len() > 64
        || pattern.iter().map(String::len).sum::<usize>() > 32 * 1024
    {
        bail!("A pattern is the command's arguments, at most 64 of them and 32 KB.");
    }
    if !pattern.starts_with(action) {
        bail!(
            "A pattern starts with its action, written out: {}",
            action.join(" ")
        );
    }
    if pattern.iter().any(|t| t.chars().any(char::is_control)) {
        bail!("Write a pattern's fixed parts on one line.");
    }
    let mut names = vec![];
    for (_, name) in pattern.iter().filter_map(|t| hole(t)) {
        if names.iter().any(|n| n == name) {
            bail!("Name each changing part once: {{{name}}} appears twice.");
        }
        names.push(name.to_owned());
    }
    if names.is_empty() {
        bail!("A pattern names what can change, for example {{body}} or body={{body}}.");
    }
    Ok(names)
}
