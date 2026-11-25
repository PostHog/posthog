use serde_json::Value;

/// The install/edit prop contract. Element-specific entries override shared
/// types (for example Chart.grid and Avatar.size). Keep this table beside
/// ELEMENTS; runtime loading deliberately does not enforce new prop rules.
const SHARED_PROPS: &str = "id:string key:string|number label:string tooltip:string cursor:string gap:number p:number px:number py:number pt:number pb:number pl:number pr:number mt:number mb:number ml:number mr:number w:length h:length minW:length maxW:length minH:length maxH:length grow:boolean shrink:boolean align:string justify:string wrap:boolean bg:string color:string borderColor:string hoverBg:string border:boolean|string radius:number clip:boolean opacity:number size:number weight:string font:string truncate:boolean nowrap:boolean selectable:boolean data:boolean onClick:function onDoubleClick:function onPress:function onRelease:function onHover:function onPointerMove:function onNudge:function onLayout:function onScroll:function hover:object active:object dropOver:object group:string groupHover:object drag:object drop:object onDragStart:function onDrag:function onDragEnd:function onDrop:function position:string top:length right:length bottom:length left:length inset:length layer:number grid:number|object span:number rowSpan:number aspect:number overflow:string shadow:string motion:object enter:string show:boolean delay:number role:string";
pub(super) const PROP_TABLE: &[(&str, &str, &str)] = &[
    ("page", "Page", ""),
    ("column", "Column", ""),
    ("row", "Row", ""),
    ("box", "Box", ""),
    (
        "scroll",
        "Scroll",
        "scrollTo:number|string scrollRevision:number|string",
    ),
    ("card", "Card", ""),
    ("text", "Text", "text:string selectable:boolean"),
    ("heading", "Heading", "text:string"),
    ("caption", "Caption", "text:string"),
    ("mono", "Mono", "text:string"),
    ("label", "Label", "text:string"),
    ("badge", "Badge", "text:string"),
    ("icon", "Icon", "name:string"),
    ("logo", "Logo", "service:string"),
    (
        "button",
        "Button",
        "label:string variant:string icon:string disabled:boolean",
    ),
    (
        "icon_button",
        "IconButton",
        "icon:string label:string! disabled:boolean variant:string",
    ),
    (
        "input",
        "Input",
        "value:string placeholder:string masked:boolean invalid:boolean onChange:function onSubmit:function",
    ),
    (
        "textarea",
        "Textarea",
        "value:string placeholder:string rows:number bare:boolean disabled:boolean submitOnEnter:boolean onChange:function onSubmit:function",
    ),
    (
        "checkbox",
        "Checkbox",
        "checked:boolean disabled:boolean onChange:function",
    ),
    (
        "toggle",
        "Toggle",
        "checked:boolean disabled:boolean onChange:function",
    ),
    (
        "select",
        "Select",
        "value:string options:options placeholder:string disabled:boolean quiet:boolean onChange:function",
    ),
    (
        "tabs",
        "Tabs",
        "items:strings selected:number underline:boolean onChange:function",
    ),
    ("progress", "Progress", "value:number"),
    ("divider", "Divider", ""),
    ("spacer", "Spacer", ""),
    ("header", "Header", "title:string subtitle:string"),
    ("empty", "Empty", "title:string detail:string"),
    ("loading", "Loading", ""),
    ("error", "ErrorMessage", "text:string"),
    ("notice", "Notice", "title:string detail:string"),
    (
        "list",
        "List",
        "count:number! row:function! scrollTo:number",
    ),
    (
        "list_row",
        "ListRow",
        "title:string subtitle:string selected:boolean",
    ),
    (
        "table",
        "Table",
        "data:string|array query:object columns:array groupBy:string collapsed:array rowHeight:number selected:any onRowClick:function onSort:function onToggleGroup:function empty:string",
    ),
    ("form", "Form", ""),
    (
        "field",
        "Field",
        "for:string hint:string optional:boolean error:string",
    ),
    ("actions", "Actions", "status:string"),
    ("section", "Section", "title:string detail:string"),
    ("link", "Link", "text:string url:string"),
    ("read_only", "ReadOnly", "value:string"),
    ("reading", "Reading", ""),
    (
        "date_picker",
        "DatePicker",
        "value:string withTime:boolean disabled:boolean onChange:function",
    ),
    (
        "time_picker",
        "TimePicker",
        "value:string disabled:boolean onChange:function",
    ),
    (
        "action_menu",
        "ActionMenu",
        "items:array onAction:function disabled:boolean",
    ),
    (
        "context_menu",
        "ContextMenu",
        "items:array onAction:function disabled:boolean",
    ),
    ("reveal", "Reveal", "open:boolean"),
    (
        "workflow_editor",
        "WorkflowEditor",
        "definition:object! step:string onClose:function!",
    ),
    (
        "workflow_outline",
        "WorkflowOutline",
        "definition:object! trace:object onEdit:function",
    ),
    (
        "block_editor",
        "BlockEditor",
        "value:array markdown:string placeholder:string readOnly:boolean onChange:function",
    ),
    (
        "scene",
        "Scene",
        "scene:string label:string! nodeSize:number edgeColor:string edgeOpacity:number selected:numbers focus:number zoom:number fit:any onSelect:function",
    ),
    (
        "chart",
        "Chart",
        "label:string! type:string data:array highlight:number format:string prefix:string suffix:string signed:boolean grid:boolean dots:boolean empty:string",
    ),
    (
        "model_selector",
        "ModelSelector",
        "selection:object onChange:function placement:string disabled:boolean profiles:array models:array efforts:array",
    ),
    ("markdown", "Markdown", "text:string selectable:boolean"),
    (
        "image",
        "Image",
        "source:string|object alt:string fit:string",
    ),
    ("hover_card", "HoverCard", ""),
    ("popover", "Popover", "open:boolean onOpenChange:function"),
    (
        "radio_group",
        "RadioGroup",
        "items:array value:any onChange:function horizontal:boolean disabled:boolean",
    ),
    (
        "rating",
        "Rating",
        "label:string! value:number max:number onChange:function disabled:boolean",
    ),
    (
        "slider",
        "Slider",
        "label:string! value:number min:number max:number step:number onChange:function onCommit:function disabled:boolean",
    ),
    (
        "accordion",
        "Accordion",
        "items:array multiple:boolean bordered:boolean onToggle:function disabled:boolean",
    ),
    ("breadcrumb", "Breadcrumb", "items:array onSelect:function"),
    (
        "pagination",
        "Pagination",
        "page:number pages:number onChange:function compact:boolean",
    ),
    (
        "description_list",
        "DescriptionList",
        "items:array columns:number bordered:boolean vertical:boolean",
    ),
    ("tag", "Tag", "text:string variant:string outline:boolean"),
    ("kbd", "Kbd", "keys:string"),
    ("avatar", "Avatar", "name:string size:number|string"),
    ("skeleton", "Skeleton", ""),
    ("spinner", "Spinner", "size:number|string"),
    (
        "sdk:ChatMessage",
        "ChatMessage",
        "message:object showActivity:boolean role:string text:string blocks:array createdAt:string|number agent:string status:string error:string",
    ),
    (
        "sdk:ToolCall",
        "ToolCall",
        "block:object open:boolean onOpenChange:function title:string text:string status:string input:any output:any",
    ),
    (
        "sdk:AgentActivity",
        "AgentActivity",
        "blocks:array run:object",
    ),
    (
        "sdk:AgentStatus",
        "AgentStatus",
        "run:object status:string onStop:function",
    ),
    (
        "sdk:ChatTranscript",
        "ChatTranscript",
        "messages:array session:string revision:number|string showActivity:boolean emptyState:string",
    ),
    (
        "sdk:ChatComposer",
        "ChatComposer",
        "value:string onChange:function onSend:function session:string run:object context:any execution:string controls:any disabled:boolean placeholder:string rows:number submitOnEnter:boolean onStop:function",
    ),
    (
        "sdk:AgentPicker",
        "AgentPicker",
        "selection:object onChange:function placement:string disabled:boolean profiles:array models:array efforts:array",
    ),
    (
        "sdk:ChatSessionList",
        "ChatSessionList",
        "sessions:array selected:string onSelect:function onRemove:function",
    ),
    (
        "sdk:Chat",
        "Chat",
        "session:string messages:array context:any execution:string onSessionChange:function onSend:function draft:string onDraftChange:function options:object title:string placeholder:string emptyState:string showActivity:boolean onNew:function onHistory:function",
    ),
];

fn prop_rules(spec: &str) -> impl Iterator<Item = (&str, &str)> {
    spec.split_whitespace()
        .filter_map(|entry| entry.split_once(':'))
}
fn prop_type(value: &Value, ty: &str) -> bool {
    ty.split('|').any(|ty| match ty {
        "any" => true,
        "string" => value.is_string(),
        "number" => value.is_number(),
        "boolean" => value.is_boolean(),
        "object" => value.is_object(),
        "array" => value.is_array(),
        "function" => value["$fn"].is_number(),
        "strings" => value
            .as_array()
            .is_some_and(|a| a.iter().all(Value::is_string)),
        "numbers" => value
            .as_array()
            .is_some_and(|a| a.iter().all(Value::is_number)),
        "options" => value.as_array().is_some_and(|a| {
            a.iter()
                .all(|v| v.is_string() || (v["value"].is_string() && v["label"].is_string()))
        }),
        "length" => {
            value.is_number()
                || value.as_str().is_some_and(|s| {
                    matches!(s, "full" | "fill" | "auto")
                        || s.strip_suffix('%')
                            .is_some_and(|n| n.parse::<f64>().is_ok())
                })
        }
        _ => false,
    })
}
pub(super) fn edit_distance(a: &str, b: &str) -> usize {
    let mut row: Vec<_> = (0..=b.chars().count()).collect();
    for (i, a) in a.chars().enumerate() {
        let mut diagonal = row[0];
        row[0] = i + 1;
        for (j, b) in b.chars().enumerate() {
            let old = row[j + 1];
            row[j + 1] = (diagonal + usize::from(a != b))
                .min(row[j] + 1)
                .min(old + 1);
            diagonal = old;
        }
    }
    *row.last().unwrap()
}
fn prop_type_name(ty: &str) -> String {
    ty.split('|')
        .map(|ty| match ty {
            "string" => "a string",
            "number" => "a number",
            "boolean" => "true or false",
            "function" => "a function",
            "object" => "an object",
            "array" => "an array",
            "strings" => "an array of strings",
            "numbers" => "an array of numbers",
            "options" => "an array of strings or { value, label } objects",
            "length" => "a number, percentage, full, fill or auto",
            _ => ty,
        })
        .collect::<Vec<_>>()
        .join(" or ")
}
type PropRules = std::collections::BTreeMap<&'static str, &'static str>;
fn element_prop_rules()
-> &'static std::collections::HashMap<&'static str, (&'static str, PropRules)> {
    static RULES: std::sync::OnceLock<
        std::collections::HashMap<&'static str, (&'static str, PropRules)>,
    > = std::sync::OnceLock::new();
    RULES.get_or_init(|| {
        PROP_TABLE
            .iter()
            .map(|(kind, name, spec)| {
                (
                    *kind,
                    (
                        *name,
                        prop_rules(SHARED_PROPS).chain(prop_rules(spec)).collect(),
                    ),
                )
            })
            .collect()
    })
}
pub(super) fn check_props_for(kind: &str, props: &Value, at: &str) -> Result<(), String> {
    let Some((name, rules)) = element_prop_rules().get(kind) else {
        return Ok(());
    };
    let props = props
        .as_object()
        .ok_or_else(|| format!("{name} props must be an object at {at}. Pass a props object."))?;
    for (key, ty) in rules {
        if ty.ends_with('!')
            && props.get(*key).is_none_or(|value| {
                value.is_null() || value.as_str().is_some_and(|s| s.trim().is_empty())
            })
        {
            let purpose = match *key {
                "label" => "its accessible name".to_owned(),
                "count" => "its number of rows".to_owned(),
                "row" => "the function that builds a row".to_owned(),
                _ => prop_type_name(ty.trim_end_matches('!')),
            };
            return Err(format!("{name} needs {key}, {purpose} ({at})."));
        }
    }
    for (key, value) in props {
        let Some(ty) = rules.get(key.as_str()) else {
            if matches!(key.as_str(), "keyframes" | "stagger") {
                return Err(format!(
                    "{name}.{key} belongs under motion at {at}. Put {key} under motion before saving."
                ));
            }
            let nearest = rules
                .keys()
                .min_by_key(|candidate| edit_distance(key, candidate))
                .unwrap();
            return Err(format!(
                "Unknown prop {name}.{key} at {at}; did you mean {nearest}? Use the props documented in SCRIPT.md and COMPONENTS.md."
            ));
        };
        if value.is_null() && !ty.ends_with('!') {
            continue;
        }
        let ty = ty.trim_end_matches('!');
        if !prop_type(value, ty) {
            return Err(format!(
                "{name}.{key} must be {} at {at}. Change {key} before saving.",
                prop_type_name(ty)
            ));
        }
    }
    if kind == "logo"
        && let Some(size) = props.get("size").and_then(Value::as_f64)
        && !(12. ..=32.).contains(&size)
    {
        return Err(format!(
            "Logo.size must be between 12 and 32 pixels at {at}."
        ));
    }
    Ok(())
}
pub(super) fn check_tree_props(node: &Value) -> Result<(), String> {
    check_props_for(
        node["t"].as_str().unwrap_or(""),
        &node["p"],
        node["at"].as_str().unwrap_or("view.js (render)"),
    )?;
    node["c"]
        .as_array()
        .into_iter()
        .flatten()
        .try_for_each(check_tree_props)
}
