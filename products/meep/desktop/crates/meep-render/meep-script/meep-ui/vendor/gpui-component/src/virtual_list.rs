pub(crate) use gpui_base::virtual_list;
pub use gpui_base::{VirtualList, VirtualListScrollHandle, h_virtual_list, v_virtual_list};

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn legacy_handle_is_the_base_type_and_a_scrollbar_handle() {
        fn accepts_base(_: gpui_base::VirtualListScrollHandle) {}
        fn accepts_scrollbar(_: impl crate::scroll::ScrollbarHandle) {}
        fn legacy_list_is_base(value: crate::VirtualList) {
            fn accepts_base(_: gpui_base::VirtualList) {}
            accepts_base(value);
        }

        let handle: crate::VirtualListScrollHandle = VirtualListScrollHandle::new();
        accepts_base(handle.clone());
        accepts_scrollbar(handle);
        let _ = legacy_list_is_base;
    }
}
