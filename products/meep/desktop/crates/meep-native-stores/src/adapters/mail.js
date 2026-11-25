// Fixed host-owned JXA adapter for host.mail's mailboxes and single messages
// (src/mail.rs); the message list is src/adapters/mail-page.applescript,
// which can address a range of messages in one event. Read-only:
// it only gets properties, never sets one, and never sends Mail a command
// (no open, activate, move, delete, send). Caller data is JSON on stdin,
// validated by the host first; nothing in it or in a message is evaluated.
// Names are Mail's scripting dictionary (Mail.app/Contents/Resources/Mail.sdef).
ObjC.import('AppKit');
const MAX_BOXES = 500, MAX_DEPTH = 8, MAX_PEOPLE = 50, MAX_ATTACHMENTS = 50, MAX_TEXT = 100000;
function fail(number, message) { const e = Error(message); e.errorNumber = number; throw e; }
function iso(d) { return d ? d.toISOString() : null; }
function people(list) {
  const names = list.name(), addresses = list.address();
  return addresses.slice(0, MAX_PEOPLE).map((address, i) => ({name: names[i] || null, address: address || null}));
}
// The names from the account down to `box`, `leaf` last. In Mail.sdef a
// mailbox has mailbox elements (`applescriptChildren`) and a `container`
// property, the mailbox holding it; `name` is the mailbox's own name only. So
// the path is read up the containers, which stops at the top: no container, or
// one that isn't a mailbox (the account).
function pathOf(box, leaf) {
  const path = [leaf];
  for (let at = box, d = 0; d < MAX_DEPTH; d++) {
    let up = null, kind, name;
    try { up = at.container(); } catch (e) { break; }
    if (!up) break;
    // JXA can't convert some classes (`container`, which Mail.sdef also has as
    // a property; an account's): then it is a mailbox if it has an account.
    try { kind = up.class(); } catch (e) { kind = null; }
    if (kind !== 'mailbox' && kind !== 'container') {
      try { up.account(); kind = 'container'; } catch (e) { break; }
    }
    try { name = up.name(); } catch (e) { break; }
    if ((kind !== 'mailbox' && kind !== 'container') || !name) break;
    path.unshift(name);
    at = up;
  }
  return path;
}
function same(a, b) { return a.length === b.length && a.every((x, i) => x === b[i]); }
// The `nth` (from 0) mailbox at `path` in an account's mailbox list. Mail's
// by-name lookup on an account doesn't find every mailbox the list names (in a
// Gmail account: Important, Starred, All Mail, Sent Mail, Spam and labels), and
// Mail may not name a nested mailbox's container, so two can share a path: the
// list is matched by name, then path, then position among those, and the
// mailbox addressed by index. Reads one name list and the matching paths.
function mailboxAt(account, path, nth) {
  const boxes = account.mailboxes, names = boxes.name(), leaf = path[path.length - 1];
  let seen = 0;
  for (let j = 0; j < names.length && j < MAX_BOXES; j++) {
    if (names[j] === leaf && same(pathOf(boxes[j], leaf), path) && seen++ === (nth || 0)) return boxes[j];
  }
  fail(-1728, "Can't get mailbox.");
}
function summary(m, box) {
  return {libraryId: m.id(), accountId: box.accountId, account: box.account, mailbox: box.mailbox,
    mailboxPath: box.path, mailboxNth: box.nth,
    subject: m.subject(), sender: m.sender(), to: people(m.toRecipients), date: iso(m.dateReceived()),
    read: m.readStatus(), flagged: m.flaggedStatus(), messageId: m.messageId()};
}
function run(argv) {
  const input = $.NSFileHandle.fileHandleWithStandardInput.readDataToEndOfFile;
  const p = JSON.parse(ObjC.unwrap($.NSString.alloc.initWithDataEncoding(input, $.NSUTF8StringEncoding)));
  try {
    // Addressing a Mail that isn't running would launch it: refuse first.
    if ($.NSRunningApplication.runningApplicationsWithBundleIdentifier('com.apple.mail').count === 0) fail(-600, 'Mail is not running');
    const mail = Application('com.apple.mail');
    const account = id => mail.accounts.byId(id);
    let result;
    switch (p.operation) {
      case 'mailboxes': {
        result = {unread: mail.inbox.unreadCount(), accounts: []};
        const ids = mail.accounts.id(), names = mail.accounts.name(), enabled = mail.accounts.enabled();
        for (let i = 0; i < ids.length; i++) {
          if (!enabled[i]) continue;
          const boxes = account(ids[i]).mailboxes;
          const unread = boxes.unreadCount();
          // A `container` (Mail.sdef: "A mailbox that contains other mailboxes")
          // holds no messages of its own, like Gmail's "[Gmail]": not listed.
          let kinds = [];
          try { kinds = boxes.class(); } catch (e) {}
          const list = [], seen = {};
          boxes.name().slice(0, MAX_BOXES).forEach((name, j) => {
            if (kinds[j] === 'container') return;
            const path = pathOf(boxes[j], name), key = JSON.stringify(path);
            seen[key] = (seen[key] || 0) + 1;
            list.push({name, path, nth: seen[key] - 1, unread: unread[j]});
          });
          result.accounts.push({id: ids[i], name: names[i], mailboxes: list});
        }
        break;
      }
      case 'message': {
        const a = account(p.message.account), path = p.message.path, nth = p.message.nth || 0;
        const m = mailboxAt(a, path, nth).messages.byId(p.message.libraryId);
        result = summary(m, {accountId: p.message.account, account: a.name(), mailbox: path[path.length - 1], path, nth});
        result.cc = people(m.ccRecipients);
        // `content` is read-only in the dictionary; getting it doesn't open the message.
        const text = m.content();
        result.text = text === null || text === undefined ? null : String(text).slice(0, MAX_TEXT);
        result.textClipped = text ? String(text).length > MAX_TEXT : false;
        const attachments = m.mailAttachments, names = attachments.name(), sizes = attachments.fileSize();
        result.attachments = names.slice(0, MAX_ATTACHMENTS).map((name, i) => ({name, size: sizes[i]}));
        break;
      }
      default: fail(-50, 'Unknown mail operation');
    }
    return JSON.stringify({ok: true, value: result});
  } catch (e) {
    return JSON.stringify({ok: false, number: e.errorNumber || 0, error: String(e)});
  }
}
