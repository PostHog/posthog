// Checks the JXA Mail adapter (mailboxes and single messages) against
// tests/fixtures/mail-fake.js, in `jsc`, with no Apple event. Run by
// `system_mail::tests::the_jxa_adapter_reads_a_fake_mail`. The message list is
// the AppleScript adapter's, checked against tests/fixtures/mail-fake.applescript.
// Prints one line per check and "all passed" at the end; throws on a failure.
function check(what, ok, detail) {
  if (!ok) throw Error('FAILED ' + what + (detail === undefined ? '' : ': ' + JSON.stringify(detail)));
  print('ok ' + what);
}
var T0 = Date.UTC(2026, 10, 1, 9, 0, 0);
function box(name, n, parent, extra) {
  var spec = {name: name, n: n, parent: parent, date: function (age) { return T0 - age * 1000; },
    id: function (age) { return (extra && extra.base || 7000) + age; }};
  for (var key in (extra || {})) spec[key] = extra[key];
  return __mailbox(spec);
}
function message(place, libraryId) {
  return __call({operation: 'message', message: {account: place.account, path: place.path, nth: place.nth || 0, libraryId: libraryId}});
}

// 1. One message by ID: its text is read once; a missing one is -1728.
__app = __mail([box('INBOX', 10, null, {base: 1000000})]);
var one = message({account: 'ACC-1', path: ['INBOX']}, 1000004);
check('a message is read by its ID, its content once', one.ok && one.value.libraryId === 1000004 && one.value.text === 'Body of 1000004'
  && one.contentReads === 1 && one.value.mailbox === 'INBOX' && one.value.accountId === 'ACC-1', one);
var gone = message({account: 'ACC-1', path: ['INBOX']}, 42);
check('a missing message is errAENoSuchObject', !gone.ok && gone.number === -1728, gone);

// 2. Mail not running: refused before Mail is ever addressed.
var addressed = __addressed.length;
__running = false;
var off = __call({operation: 'mailboxes'});
check('not running is -600 and Mail is never addressed', !off.ok && off.number === -600 && __addressed.length === addressed, off);
__running = true;
check('Mail is addressed by bundle ID only', __addressed.every(function (a) { return a === 'com.apple.mail'; }), __addressed.slice(0, 3));

// 3. Mailboxes: enabled accounts, names and unread counts.
__app = __mail([box('INBOX', 3, null), box('Small', 5, null)]);
var boxes = __call({operation: 'mailboxes'});
check('mailboxes lists the account\'s boxes', boxes.ok && boxes.value.accounts[0].mailboxes.length === 2, boxes.value);

// 4. Nested mailboxes, as Gmail's are: "[Gmail]" is a container holding the
// special folders, a label holds another, and "Alerts" is in two accounts.
// Mail's by-name lookup on the account misses nested ones (see the fake).
var gmail = box('[Gmail]', 0, null, {kind: 'container'});
var github = box('Github', 2, null, {base: 8100});
var gmailBoxes = [box('INBOX', 3, null, {base: 8000}), gmail, box('Important', 4, gmail, {base: 8200}),
  box('Sent Mail', 60, gmail, {base: 8300}), box('All Mail', 5, gmail, {base: 8400}),
  github, box('Alerts', 6, github, {base: 8500}), box('Spam', 0, gmail, {base: 8600})];
var icloud = [box('INBOX', 2, null, {base: 9000}), box('Alerts', 1, null, {base: 9100})];
var firsts = {'INBOX': 8000, 'Important': 8200, 'Sent Mail': 8300, 'All Mail': 8400, 'Github': 8100, 'Alerts': 8500};
['null', 'throw', 'account'].forEach(function (top) {
  __topLevel = top === 'null' ? null : top;
  __app = __mail(icloud, [{id: 'ACC-2', name: 'Gmail', boxes: gmailBoxes}]);
  var listed = __call({operation: 'mailboxes'});
  var g = listed.value.accounts[1];
  var paths = JSON.stringify(g.mailboxes.map(function (m) { return m.path; }));
  check('nested mailboxes list their path, without the container (' + top + ')', listed.ok && g.name === 'Gmail'
    && paths === '[["INBOX"],["[Gmail]","Important"],["[Gmail]","Sent Mail"],["[Gmail]","All Mail"],["Github"],["Github","Alerts"],["[Gmail]","Spam"]]',
    paths);
  check('listing paths stays small (' + top + ')', listed.reads < 80, listed.reads);
  // Every listed mailbox with messages reads a message back by its path.
  g.mailboxes.forEach(function (m) {
    if (!(m.name in firsts)) return;
    var got = message({account: 'ACC-2', path: m.path, nth: m.nth}, firsts[m.name]);
    check('reads back Gmail ' + m.path.join('/') + ' (' + top + ')', got.ok && got.value.mailbox === m.name
      && JSON.stringify(got.value.mailboxPath) === JSON.stringify(m.path), got);
  });
});
var cloudAlert = message({account: 'ACC-1', path: ['Alerts']}, 9100);
var gmailAlertInCloud = message({account: 'ACC-1', path: ['Alerts']}, 8500);
check('same-named mailboxes stay apart', cloudAlert.ok && !gmailAlertInCloud.ok && gmailAlertInCloud.number === -1728, [cloudAlert.ok, gmailAlertInCloud]);
[['Sent Mail'], ['Alerts'], ['Nope', 'Sent Mail']].forEach(function (path) {
  var wrong = message({account: 'ACC-2', path: path}, 8300);
  check('no mailbox at ' + path.join('/') + ' is errAENoSuchObject', !wrong.ok && wrong.number === -1728, wrong);
});

// 5. Two mailboxes whose container Mail doesn't name share a path: each is
// listed with its position among them and reads back as itself.
__topLevel = null;
__app = __mail([box('INBOX', 1, null, {base: 9500}), box('Alerts', 2, null, {base: 9600}), box('Alerts', 3, null, {base: 9700})]);
var listedTwins = __call({operation: 'mailboxes'}).value.accounts[0].mailboxes;
check('same paths are numbered in list order', JSON.stringify(listedTwins.map(function (m) { return m.nth; })) === '[0,0,1]', listedTwins);
var twin = message({account: 'ACC-1', path: ['Alerts'], nth: 1}, 9701);
check('a message is read from the second', twin.ok && twin.value.libraryId === 9701 && twin.value.mailboxNth === 1, twin);
var notFirst = message({account: 'ACC-1', path: ['Alerts'], nth: 0}, 9701);
check('and not from the first', !notFirst.ok && notFirst.number === -1728, notFirst);
var third = message({account: 'ACC-1', path: ['Alerts'], nth: 2}, 9701);
check('no third one is errAENoSuchObject', !third.ok && third.number === -1728, third);
print('all passed');
