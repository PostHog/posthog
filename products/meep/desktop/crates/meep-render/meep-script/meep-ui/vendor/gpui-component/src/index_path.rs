pub use gpui_base::IndexPath;

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn legacy_export_is_the_base_type() {
        fn accepts_base(_: gpui_base::IndexPath) {}

        let legacy: crate::IndexPath = IndexPath::new(2).section(1).column(3);
        accepts_base(legacy);
    }
}
