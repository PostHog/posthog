use super::*;

fn source_location(text: &str) -> Option<String> {
    text.find("view.js:").map(|at| {
        text[at..]
            .chars()
            .take_while(|c| c.is_ascii_digit() || "view.js:".contains(*c))
            .collect()
    })
}
fn exception_message(name: &str, message: &str, stack: &str) -> String {
    let at = source_location(stack)
        .map(|at| format!(" at {at}"))
        .unwrap_or_default();
    let undefined = message
        .strip_suffix(" is not defined")
        .map(|s| s.trim_matches(['\'', '"']));
    let guidance = if name == "SyntaxError" {
        Some(format!(
            "JavaScript syntax error{at}: {}. Check nearby brackets, commas and function syntax.",
            message
                .lines()
                .next()
                .unwrap_or(message)
                .trim_end_matches(['.', '!', '?'])
        ))
    } else if let Some(identifier) = undefined {
        if identifier == "Intl" {
            Some(format!(
                "Intl is unavailable in views{at}. Use the Date and Number formatting recipe in SCRIPT.md under JavaScript APIs."
            ))
        } else if identifier.chars().next().is_some_and(char::is_uppercase) {
            let nearest = PROP_TABLE
                .iter()
                .map(|(_, name, _)| *name)
                .min_by_key(|name| edit_distance(&identifier.to_lowercase(), &name.to_lowercase()))
                .unwrap_or("Text");
            Some(format!(
                "Unknown element {identifier}{at}; did you mean {nearest}? Use the SDK names in SCRIPT.md."
            ))
        } else {
            Some(format!(
                "The view could not read {identifier}{at}. Check the variable name and where it is declared."
            ))
        }
    } else {
        None
    };
    let original = if stack.trim().is_empty() {
        message.to_owned()
    } else {
        format!("{message}\n{}", stack.trim_end())
    };
    guidance.map_or_else(
        || original.clone(),
        |main| format!("{main}\nJavaScript detail: {original}"),
    )
}
pub(super) fn describe(ctx: &Ctx<'_>, error: rquickjs::Error) -> String {
    if !matches!(error, rquickjs::Error::Exception) {
        return error.to_string();
    }
    let value = ctx.catch();
    if let Some(exception) = value.as_exception() {
        let message = exception
            .message()
            .filter(|s| !s.is_empty())
            .unwrap_or_else(|| "Uncaught exception".into());
        let stack = exception.stack().unwrap_or_default();
        let name: String = exception.as_object().get("name").unwrap_or_default();
        return exception_message(&name, &message, &stack);
    }
    if value.is_null() || value.is_undefined() {
        return STOPPED.into();
    }
    value
        .as_string()
        .and_then(|s| s.to_string().ok())
        .unwrap_or_else(|| format!("{value:?}"))
}
