use cymbal_domain::ExceptionProperties;

use crate::exception::ResolutionExceptionProperties;

#[derive(Debug, Clone, Default)]
pub struct PropertiesResolver;

impl PropertiesResolver {
    pub fn resolve_domain(&self, mut event: ExceptionProperties) -> ExceptionProperties {
        let Some(exception_list) = event.exception_list.as_ref() else {
            return event;
        };

        event.exception_functions = Some(exception_list.get_unique_functions());
        event.exception_sources = Some(exception_list.get_unique_sources());
        event.exception_types = Some(exception_list.get_unique_types());
        event.exception_messages = Some(exception_list.get_unique_messages());
        event.exception_releases = exception_list.get_release_map();
        event.exception_handled = Some(exception_list.get_is_handled());
        event
    }

    pub fn resolve(
        &self,
        event: ResolutionExceptionProperties,
    ) -> Result<ExceptionProperties, serde_json::Error> {
        let release_map = event.exception_list.get_release_map();
        let properties = serde_json::to_value(event)?;
        let domain_event: ExceptionProperties = serde_json::from_value(properties)?;
        let mut resolved = self.resolve_domain(domain_event);
        if !release_map.is_empty() {
            resolved.exception_releases = release_map;
        }
        Ok(resolved)
    }
}

#[cfg(test)]
mod tests {
    use serde_json::{json, Value};

    use super::*;

    fn properties_from_value(value: Value) -> ExceptionProperties {
        ExceptionProperties::from_map(value.as_object().unwrap().clone()).unwrap()
    }

    #[test]
    fn materializes_searchable_exception_properties() {
        let properties = properties_from_value(json!({
            "$exception_list": [
                {
                    "type": "TypeError",
                    "value": "first boom",
                    "mechanism": { "handled": true },
                    "stacktrace": {
                        "frames": [
                            {
                                "filename": "app.js",
                                "function": "runExample",
                                "lineno": 10,
                                "colno": 5
                            },
                            {
                                "filename": "vendor.js",
                                "function": "vendorCall",
                                "in_app": false
                            }
                        ]
                    }
                },
                {
                    "type": "TypeError",
                    "value": "second boom",
                    "stacktrace": {
                        "frames": [
                            {
                                "source": "src/app.ts",
                                "resolved_name": "runExample"
                            }
                        ]
                    }
                }
            ]
        }));

        let resolved = serde_json::to_value(PropertiesResolver.resolve_domain(properties)).unwrap();

        assert_eq!(
            resolved.pointer("/$exception_types"),
            Some(&json!(["TypeError"]))
        );
        assert_eq!(
            resolved.pointer("/$exception_values"),
            Some(&json!(["first boom", "second boom"]))
        );
        assert_eq!(
            resolved.pointer("/$exception_functions"),
            Some(&json!(["runExample"]))
        );
        assert_eq!(
            resolved.pointer("/$exception_sources"),
            Some(&json!(["app.js", "src/app.ts"]))
        );
        assert_eq!(resolved.pointer("/$exception_handled"), Some(&json!(true)));
    }

    #[test]
    fn leaves_events_without_exception_list_unchanged() {
        let properties = properties_from_value(json!({
            "$exception_message": "boom"
        }));

        let resolved = PropertiesResolver.resolve_domain(properties.clone());

        assert_eq!(resolved, properties);
    }
}
