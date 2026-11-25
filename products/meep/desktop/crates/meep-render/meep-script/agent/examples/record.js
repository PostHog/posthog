// A complete local record editor: sized native fields, a dropdown, a segmented
// status, multiline notes, validation, discard/save and a persistent draft.
// Replace save() with an explicitly permitted source mutation for a remote
// record, and never report remote success before the tool result confirms it.
const DEFAULTS = { name: "Milo", category: "Dogs", tags: "Friendly, Adoptable", status: 0, notes: "" };
const STATUSES = ["Available", "Pending", "Sold"];
view({
  state: { saved: DEFAULTS, draft: DEFAULTS, attempted: false },
  commands: {
    save() { if (!save()) throw new Error("Enter a name."); return getState(); },
    reset() { reset(); return getState(); },
  },
  inspect: (s) => ({ saved: s.saved }),
  keys: { "cmd-s": save },
  render(s) {
    const d = s.draft;
    const dirty = JSON.stringify(d) !== JSON.stringify(s.saved);
    const invalid = s.attempted && !d.name.trim();
    const edit = (field) => (value) => setState((st) => ({ draft: Object.assign({}, st.draft, { [field]: value }) }));
    return Page(
      Form({ id: "pet-form", grow: true },
        Header({ title: "Edit pet", subtitle: "Profile and availability", pb: 0 }),
        ReadOnly("Pet ID", "12345679", { id: "copy-pet-id" }),
        Scroll({ id: "record-fields", gap: 18, px: 2, py: 2 },
          Field({ id: "pet-name-field", label: "Name", for: "pet-name", error: invalid ? "Enter a name." : "" },
            Input({ id: "pet-name", label: "Pet name", placeholder: "Pet name", value: d.name, invalid, onChange: edit("name") })),
          Field({ id: "pet-category-field", label: "Category" },
            Select({ id: "pet-category", label: "Pet category", value: d.category, options: ["Dogs", "Cats", "Other"], onChange: edit("category") })),
          Field({ id: "pet-tags-field", label: "Tags", for: "pet-tags", optional: true, hint: "Separate tags with commas." },
            Input({ id: "pet-tags", label: "Pet tags", placeholder: "Add tags…", value: d.tags, onChange: edit("tags") })),
          Field({ id: "pet-status-field", label: "Status" },
            Tabs({ id: "pet-status", items: STATUSES, selected: d.status, onChange: edit("status") })),
          Field({ id: "pet-notes-field", label: "Care notes", for: "pet-notes", optional: true },
            Textarea({ id: "pet-notes", label: "Care notes", placeholder: "Care instructions or other details…", rows: 4, value: d.notes, onChange: edit("notes") }))),
        Actions({ status: dirty ? "Unsaved changes" : "Saved" },
          Button("Discard", { id: "pet-discard", variant: "secondary", disabled: !dirty, onClick: reset }),
          Button("Save changes", { id: "pet-save", variant: "primary", disabled: !dirty, onClick: save }))));
  },
});

function save() {
  const { draft } = getState();
  if (!draft.name.trim()) {
    setState({ attempted: true });
    host.focus("pet-name");
    return false;
  }
  setState({ saved: draft, attempted: false });
  return true;
}
function reset() { setState((s) => ({ draft: s.saved, attempted: false })); }
