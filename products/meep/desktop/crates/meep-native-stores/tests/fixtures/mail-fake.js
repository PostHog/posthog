// Test-only stand-in for Mail's scripting objects, loaded before the real
// JXA adapter (src/adapters/mail.js: mailboxes and single messages) in
// JavaScriptCore's `jsc` shell by
// `system_mail::tests`. It shadows the three globals the adapter touches
// (`ObjC`, `$`, `Application`), so no Apple event can be sent: `jsc` has no
// scripting bridge at all. Production never loads this file.
//
// It mimics the specifier behaviour the adapter relies on: property getters are
// functions, element lists index from either end and answer `length`, `byId` and
// `byName`, and a bulk getter on a list (`list.name()`) returns an array. Every
// getter call counts as one Apple event in `__reads`.
//
// Mailboxes nest as in Mail.sdef: a mailbox's `container` is the mailbox holding
// it, its `name` is its own name only, and a `container` (class) holds only
// mailboxes. An account's `mailboxes` lists nested ones too, but its `byName`
// finds only top-level ones, as Mail's does for Gmail's "[Gmail]" folders.
// What a top-level mailbox's `container` answers is unconfirmed, so
// `__topLevel` picks one: null, 'throw' (no such object) or 'account'.
var __reads = 0, __contentReads = 0, __input = '', __running = true, __addressed = [], __topLevel = null;
var ObjC = { import: function () {}, unwrap: function (x) { return x; } };
var $ = {
  NSUTF8StringEncoding: 4,
  NSFileHandle: { fileHandleWithStandardInput: { get readDataToEndOfFile() { return __input; } } },
  NSString: { alloc: { initWithDataEncoding: function (data) { return data; } } },
  NSRunningApplication: {
    runningApplicationsWithBundleIdentifier: function () { return { count: __running ? 1 : 0 }; },
  },
};
function __missing() { var e = Error("Can't get object."); e.errorNumber = -1728; throw e; }
function __get(value) { return function () { __reads++; return value; }; }
// A lazily built list of `n` items; `item(k)` builds item k (0 = first in Mail's order).
function __list(n, item, byId) {
  var cache = {};
  var at = function (k) {
    if (k < 0) k = n + k;
    if (k < 0 || k >= n) return new Proxy({}, { get: function () { return __missing; } });
    return cache[k] || (cache[k] = item(k));
  };
  return new Proxy({}, {
    get: function (_, key) {
      if (key === 'length') { __reads++; return n; }
      if (key === 'byId') return function (id) { var k = byId(id); return k === null ? at(n) : at(k); };
      if (typeof key === 'string' && /^-?\d+$/.test(key)) return at(Number(key));
      return undefined;
    },
  });
}
// A mailbox of `n` messages. `date(k)` is message k's date in ms (k = 0 is
// newest), `newestFirst` is Mail's order, `read(k)` its read state.
// `spec.parent` is the mailbox holding it; `spec.kind` 'container' holds no messages.
function __mailbox(spec) {
  var box = { name: __get(spec.name), unreadCount: __get(spec.unread || 0), class: __get(spec.kind || 'mailbox') };
  // As in Mail: JXA can't convert a container's class (Mail.sdef also has a
  // property named `container`).
  if (spec.kind === 'container') box.class = function () { __reads++; var e = Error("Can't convert types."); e.errorNumber = -1700; throw e; };
  box.container = function () {
    __reads++;
    if (spec.parent) return spec.parent;
    if (__topLevel === 'throw') __missing();
    return __topLevel === 'account' ? box.__account : null;
  };
  box.__parent = spec.parent || null;
  var newestFirst = spec.newestFirst !== false;
  var message = function (age) {
    var id = spec.id ? spec.id(age) : 1000000 + age;
    var m = {
      id: __get(id), subject: __get('Subject ' + id), sender: __get('Ada <ada@example.com>'),
      dateReceived: function () { __reads++; return new Date(spec.date(age)); },
      readStatus: __get(spec.read ? spec.read(age) : true), flaggedStatus: __get(false),
      messageId: __get('m' + id + '@example.com'),
      content: function () { __reads++; __contentReads++; return 'Body of ' + id; },
      mailbox: function () { __reads++; return box; },
      toRecipients: { name: __get(['Me']), address: __get(['me@example.com']) },
      ccRecipients: { name: __get([]), address: __get([]) },
      mailAttachments: { name: __get([]), fileSize: __get([]) },
    };
    m.__age = age;
    return m;
  };
  box.messages = __list(spec.n || 0, function (k) { return message(newestFirst ? k : spec.n - 1 - k); }, function (id) {
    for (var age = 0; age < spec.n; age++) if ((spec.id ? spec.id(age) : 1000000 + age) === id) return newestFirst ? age : spec.n - 1 - age;
    return null;
  });
  box.account = function () { __reads++; return box.__account; };
  return box;
}
function __account(id, name, boxes) {
  // Like Mail, JXA can't convert an account's class either.
  var account = { id: __get(id), name: __get(name), class: function () { __reads++; var e = Error("Can't convert types."); e.errorNumber = -1700; throw e; } };
  boxes.forEach(function (b) { b.__account = account; });
  var reads = __reads;
  var names = boxes.map(function (b) { return b.name(); }), unread = boxes.map(function (b) { return b.unreadCount(); });
  // In bulk, Mail answers every class, containers' too.
  var kinds = boxes.map(function (b) { try { return b.class(); } catch (e) { return 'container'; } });
  __reads = reads;
  var list = __list(boxes.length, function (k) { return boxes[k]; }, function () { return null; });
  account.mailboxes = new Proxy({}, {
    get: function (_, key) {
      if (key === 'name') return __get(names);
      if (key === 'unreadCount') return __get(unread);
      if (key === 'class') return __get(kinds);
      if (key === 'byName') return function (n) {
        var top = boxes.filter(function (b, k) { return !b.__parent && names[k] === n; })[0];
        return top || new Proxy({}, { get: function () { return __missing; } });
      };
      return list[key];
    },
  });
  return account;
}
// `boxes` are the first account's (ACC-1, "iCloud"); `more` adds accounts as
// {id, name, boxes}. The unified inbox is the first account's first mailbox.
function __mail(boxes, more) {
  var accounts = [__account('ACC-1', 'iCloud', boxes)].concat((more || []).map(function (a) { return __account(a.id, a.name, a.boxes); }));
  var reads = __reads;
  var ids = accounts.map(function (a) { return a.id(); }), names = accounts.map(function (a) { return a.name(); });
  __reads = reads;
  return {
    inbox: boxes[0],
    accounts: {
      id: __get(ids), name: __get(names), enabled: __get(ids.map(function () { return true; })),
      byId: function (id) { return accounts[ids.indexOf(id)] || {}; },
    },
  };
}
var __app = null;
function Application(name) { __addressed.push(name); return __app; }
// Runs one adapter call; returns its parsed answer and the getter calls it made.
function __call(input) {
  __reads = 0; __contentReads = 0;
  __input = JSON.stringify(input);
  var answer = JSON.parse(run([]));
  answer.reads = __reads; answer.contentReads = __contentReads;
  return answer;
}
