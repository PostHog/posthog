use crate::frames::Frame;

pub const MAX_PATH_CHARS: usize = 1024;

/// The most complete path known for a frame, for matching against the repository file list.
pub fn best_path(frame: &Frame) -> Option<String> {
    let path = if let Some(path) = frame.build_path.as_deref().or(frame.raw_path.as_deref()) {
        path.to_string()
    } else if frame.lang == "java" {
        // A Java or Kotlin frame names only its file, so the package gives the folders.
        java_path(frame.module.as_deref()?, frame.source.as_deref())?
    } else {
        frame.source.clone()?
    };
    clean(&path)
}

/// Build `com/acme/billing/Invoice.kt` from the class `com.acme.billing.InvoiceKt` and the source
/// file name. Returns `None` when the class has no package or the file name cannot be known.
pub fn java_path(class: &str, source: Option<&str>) -> Option<String> {
    let (package, simple_name) = class.rsplit_once('.')?;
    if package.is_empty() {
        return None;
    }
    let file = match source.filter(|source| *source != "SourceFile" && has_extension(source)) {
        Some(source) => source.to_string(),
        None => {
            // Kotlin compiles top-level functions of Invoice.kt into the class InvoiceKt.
            let outer = simple_name.split('$').next().unwrap_or(simple_name);
            let stem = outer.strip_suffix("Kt").filter(|stem| !stem.is_empty())?;
            format!("{stem}.kt")
        }
    };
    Some(format!("{}/{file}", package.replace('.', "/")))
}

fn has_extension(file: &str) -> bool {
    file.rsplit_once('.')
        .is_some_and(|(stem, extension)| !stem.is_empty() && !extension.is_empty())
}

fn clean(path: &str) -> Option<String> {
    let path = path.split('?').next().unwrap_or(path).replace('\\', "/");
    let usable =
        !path.is_empty() && !path.starts_with('<') && path.chars().count() <= MAX_PATH_CHARS;
    usable.then_some(path)
}

#[cfg(test)]
mod tests {
    use serde_json::json;

    use super::*;

    fn frame(value: serde_json::Value) -> Frame {
        let mut base = json!({
            "raw_id": "abc/0",
            "mangled_name": "run",
            "in_app": true,
            "resolved": true,
            "lang": "javascript",
        });
        base.as_object_mut()
            .unwrap()
            .extend(value.as_object().unwrap().clone());
        serde_json::from_value(base).unwrap()
    }

    #[test]
    fn picks_the_most_complete_path_of_each_frame_kind() {
        let mut python = frame(json!({"lang": "python", "source": "orders/views.py"}));
        python.raw_path = Some("/app/acme_api/orders/views.py".to_string());
        let cases = [
            (
                "native uses the build path",
                frame(
                    json!({"lang": "rust", "source": "payment.rs", "build_path": "/home/runner/work/shop/rust/src/payment.rs"}),
                ),
                Some("/home/runner/work/shop/rust/src/payment.rs"),
            ),
            (
                "python uses the raw path",
                python,
                Some("/app/acme_api/orders/views.py"),
            ),
            (
                "java builds the path from the package",
                frame(
                    json!({"lang": "java", "source": "SourceFile", "module": "com.acme.billing.InvoiceKt"}),
                ),
                Some("com/acme/billing/Invoice.kt"),
            ),
            (
                "java without a package has no path",
                frame(json!({"lang": "java", "source": "Main.java", "module": "Main"})),
                None,
            ),
            (
                "javascript uses the source, cleaned",
                frame(json!({"source": "webpack://acme-web/.\\src\\index.tsx?v=3"})),
                Some("webpack://acme-web/./src/index.tsx"),
            ),
            (
                "a synthetic source has no path",
                frame(json!({"source": "<anonymous>"})),
                None,
            ),
        ];

        for (name, frame, expected) in cases {
            assert_eq!(best_path(&frame).as_deref(), expected, "{name}");
        }
    }

    #[test]
    fn builds_java_paths_from_the_class_and_source() {
        let cases = [
            (
                "com.acme.billing.InvoiceKt",
                Some("SourceFile"),
                Some("com/acme/billing/Invoice.kt"),
            ),
            (
                "com.acme.billing.Invoice$Line",
                Some("Invoice.kt"),
                Some("com/acme/billing/Invoice.kt"),
            ),
            ("com.acme.billing.Invoice", None, None),
            ("Main", Some("Main.java"), None),
        ];
        for (class, source, expected) in cases {
            assert_eq!(java_path(class, source).as_deref(), expected, "{class}");
        }
    }
}
