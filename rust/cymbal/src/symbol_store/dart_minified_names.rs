use std::collections::HashMap;

use serde::Deserialize;

pub fn parse_dart_minified_names(sourcemap_json: &str) -> Option<HashMap<String, String>> {
    let parsed: Dart2JsSourceMap = serde_json::from_str(sourcemap_json).ok()?;
    let ext = parsed.x_org_dartlang_dart2js?;
    let minified_names = ext.minified_names?;

    let global_str = minified_names.global?;
    let parts: Vec<&str> = global_str.split(',').collect();

    let mut result = HashMap::new();
    for chunk in parts.chunks(2) {
        if let [minified, index_str] = chunk {
            if let Ok(index) = index_str.parse::<usize>() {
                if let Some(original) = parsed.names.get(index) {
                    result.insert(minified.to_string(), original.clone());
                }
            }
        }
    }

    if result.is_empty() {
        None
    } else {
        Some(result)
    }
}

pub fn lookup_minified_type(
    minified_names: &HashMap<String, String>,
    minified_type: &str,
) -> Option<String> {
    let minified_id = minified_type.strip_prefix("minified:")?;
    minified_names.get(minified_id).cloned()
}

#[derive(Deserialize)]
struct Dart2JsSourceMap {
    #[serde(default)]
    names: Vec<String>,
    #[serde(rename = "x_org_dartlang_dart2js")]
    x_org_dartlang_dart2js: Option<Dart2JsExtension>,
}

#[derive(Deserialize)]
struct Dart2JsExtension {
    minified_names: Option<MinifiedNames>,
}

#[derive(Deserialize)]
struct MinifiedNames {
    global: Option<String>,
    #[allow(dead_code)]
    instance: Option<String>,
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_parse_dart_minified_names() {
        let sourcemap = r#"{
            "version": 3,
            "names": ["ClassA", "methodFoo", "UnsupportedError", "MyException"],
            "x_org_dartlang_dart2js": {
                "minified_names": {
                    "global": "A,0,BA,2,BE,3",
                    "instance": "a,1"
                }
            }
        }"#;

        let result = parse_dart_minified_names(sourcemap).unwrap();
        assert_eq!(result.get("A"), Some(&"ClassA".to_string()));
        assert_eq!(result.get("BA"), Some(&"UnsupportedError".to_string()));
        assert_eq!(result.get("BE"), Some(&"MyException".to_string()));
    }

    #[test]
    fn test_lookup_minified_type() {
        let mut names = HashMap::new();
        names.insert("BA".to_string(), "UnsupportedError".to_string());
        names.insert("BE".to_string(), "MyException".to_string());

        assert_eq!(
            lookup_minified_type(&names, "minified:BA"),
            Some("UnsupportedError".to_string())
        );
        assert_eq!(
            lookup_minified_type(&names, "minified:BE"),
            Some("MyException".to_string())
        );
        assert_eq!(lookup_minified_type(&names, "minified:XX"), None);
        assert_eq!(lookup_minified_type(&names, "NotMinified"), None);
    }

    #[test]
    fn test_parse_missing_extension() {
        let sourcemap = r#"{
            "version": 3,
            "names": ["ClassA"]
        }"#;

        assert!(parse_dart_minified_names(sourcemap).is_none());
    }
}
