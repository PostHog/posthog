use gpui_kit::Keystroke;

#[derive(Clone, Copy, PartialEq, Eq, Debug)]
pub struct Shortcut {
    pub key: &'static str,
    pub control: bool,
    pub alt: bool,
    pub shift: bool,
    pub cmd: bool,
}

impl Shortcut {
    pub const fn key(key: &'static str) -> Self {
        Self {
            key,
            control: false,
            alt: false,
            shift: false,
            cmd: false,
        }
    }

    pub const fn cmd(key: &'static str) -> Self {
        Self {
            cmd: true,
            ..Self::key(key)
        }
    }

    pub const fn control(self) -> Self {
        Self {
            control: true,
            ..self
        }
    }

    pub const fn alt(self) -> Self {
        Self { alt: true, ..self }
    }

    pub const fn shift(self) -> Self {
        Self {
            shift: true,
            ..self
        }
    }

    pub fn matches(&self, keystroke: &Keystroke) -> bool {
        let m = &keystroke.modifiers;
        keystroke.key.eq_ignore_ascii_case(self.key)
            && m.control == self.control
            && m.alt == self.alt
            && m.shift == self.shift
            && m.platform == self.cmd
    }

    pub fn binding(&self) -> String {
        let mut parts = vec![];
        for (on, name) in [
            (self.control, "ctrl"),
            (self.alt, "alt"),
            (self.shift, "shift"),
            (self.cmd, "cmd"),
        ] {
            if on {
                parts.push(name);
            }
        }
        parts.push(self.key);
        parts.join("-")
    }

    pub fn label(&self) -> String {
        let mut label = String::new();
        for (on, mark) in [
            (self.control, '⌃'),
            (self.alt, '⌥'),
            (self.shift, '⇧'),
            (self.cmd, '⌘'),
        ] {
            if on {
                label.push(mark);
            }
        }
        label.push_str(&key_label(self.key));
        label
    }

    pub fn hint(&self, action: &str) -> String {
        format!("{action} · {}", self.label())
    }
}

fn key_label(key: &str) -> String {
    match key {
        "enter" => "↵".into(),
        "escape" => "Esc".into(),
        "space" => "Space".into(),
        "tab" => "⇥".into(),
        "backspace" => "⌫".into(),
        "up" => "↑".into(),
        "down" => "↓".into(),
        "left" => "←".into(),
        "right" => "→".into(),
        _ => key.to_uppercase(),
    }
}

pub const SETTINGS: Shortcut = Shortcut::cmd(",");
pub const TOGGLE_SIDEBAR: Shortcut = Shortcut::cmd("s").control();
pub const CLOSE_WINDOW: Shortcut = Shortcut::cmd("w");
pub const QUIT: Shortcut = Shortcut::cmd("q");
pub const HIDE: Shortcut = Shortcut::cmd("h");
pub const HIDE_OTHERS: Shortcut = Shortcut::cmd("h").alt();
pub const MINIMIZE: Shortcut = Shortcut::cmd("m");
pub const FULL_SCREEN: Shortcut = Shortcut::cmd("f").control();
pub const BACK: Shortcut = Shortcut::key("escape");
pub const SEND_LATER: Shortcut = Shortcut::cmd("enter");

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn label_binding_and_match_come_from_one_definition() {
        let overview = Shortcut::cmd("o").control();
        assert_eq!(overview.label(), "⌃⌘O");
        assert_eq!(overview.binding(), "ctrl-cmd-o");
        assert!(overview.matches(&Keystroke::parse("ctrl-cmd-o").unwrap()));
        assert!(!overview.matches(&Keystroke::parse("cmd-o").unwrap()));
        assert_eq!(SEND_LATER.label(), "⌘↵");
        assert_eq!(HIDE_OTHERS.label(), "⌥⌘H");
    }
}
