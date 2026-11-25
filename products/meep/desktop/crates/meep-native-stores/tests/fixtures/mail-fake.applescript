-- Fake Mail -------------------------------------------------------------------
-- Test-only stand-in for the "Mail" section of src/adapters/mail-page.applescript.
-- `system_mail::tests` runs the adapter's own code with this section in place
-- of the real one: it addresses no application, so no Apple event is sent.
-- Production never loads this file.
--
-- The model is picked by the MEEP_MAIL_FAKE environment variable:
--   big     one account (ACC-1): INBOX of 20000 messages, three to a second,
--           IDs rising with age inside a second (Mail's IDs aren't
--           date-ordered); "Old", the same in oldest-first order; "Burst",
--           120 messages in one second then one a second (300); "Unread", 1000
--           with every 7th unread; "Empty"; "One".
--   nested  ACC-1 (iCloud: INBOX, Alerts) and ACC-2 (Gmail: INBOX, a "[Gmail]"
--           container holding Important and Sent Mail, a label "Github" holding
--           "Alerts"), and two "Alerts" side by side in ACC-3, which Mail names
--           no container for.
--   stall   INBOX of 40 messages whose 6th newest headers take too long.
--   hostile INBOX of 3 messages whose texts hold the adapter's separators,
--           quotes, line breaks, emoji and 5000 characters.
--   off     Mail isn't running.
-- Every handler that stands for an Apple event adds one to `fakeEvents`.
global mailApp, fakeModel, fakeEvents, fakeT0, fakeTopLevel

on openMail()
	set fakeEvents to 0
	set fakeName to system attribute "MEEP_MAIL_FAKE"
	if fakeName is "off" then error "Mail is not running" number -600
	set fakeT0 to localDate("2026 11 1 32400")
	set fakeTopLevel to missing value
	if fakeName is "big" then
		set fakeModel to {fakeAccount("ACC-1", "iCloud", {¬
			fakeBox("INBOX", 0, 20000, true, "thirds", "plain", 1000000, "all"), ¬
			fakeBox("Old", 0, 20000, false, "thirds", "plain", 1000000, "all"), ¬
			fakeBox("Burst", 0, 300, true, "burst", "burst", 5000, "all"), ¬
			fakeBox("Unread", 0, 1000, true, "linear", "plain", 3000000, "every7"), ¬
			fakeBox("Empty", 0, 0, true, "linear", "plain", 1, "all"), ¬
			fakeBox("One", 0, 1, true, "linear", "plain", 4000000, "all")})}
	else if fakeName is "nested" then
		set fakeModel to {¬
			fakeAccount("ACC-1", "iCloud", {fakeBox("INBOX", 0, 2, true, "linear", "plain", 9000, "all"), fakeBox("Alerts", 0, 1, true, "linear", "plain", 9100, "all")}), ¬
			fakeAccount("ACC-2", "Gmail", {fakeBox("INBOX", 0, 3, true, "linear", "plain", 8000, "all"), fakeBox("[Gmail]", 0, 0, true, "container", "plain", 1, "all"), ¬
				fakeBox("Important", 2, 4, true, "linear", "plain", 8200, "all"), fakeBox("Sent Mail", 2, 60, true, "linear", "plain", 8300, "all"), ¬
				fakeBox("Github", 0, 2, true, "linear", "plain", 8100, "all"), fakeBox("Alerts", 5, 6, true, "linear", "plain", 8500, "all")}), ¬
			fakeAccount("ACC-3", "Work", {fakeBox("Alerts", 0, 2, true, "linear", "plain", 9600, "all"), fakeBox("Alerts", 0, 3, true, "linear", "plain", 9700, "all")})}
	else if fakeName is "stall" then
		set fakeModel to {fakeAccount("ACC-1", "iCloud", {fakeBox("INBOX", 0, 40, true, "linear", "plain", 1000, "all")})}
	else if fakeName is "hostile" then
		set fakeModel to {fakeAccount("ACC-1", "iCloud", {fakeBox("INBOX", 0, 3, true, "linear", "plain", 1000, "all")})}
	else
		error "No fake Mail named " & fakeName number -2700
	end if
	set mailApp to missing value
end openMail

on fakeAccount(accountId, accountName, boxes)
	return {fakeKind:"account", accountId:accountId, accountName:accountName, boxes:boxes}
end fakeAccount

-- A mailbox: its name, the index of the mailbox holding it (0: none), how many
-- messages, Mail's order, how dates and IDs go, the first ID, read states.
-- `dateKind` "container" makes it a container, holding no messages.
on fakeBox(boxName, parentIndex, n, newest, dateKind, idKind, base, reads)
	return {boxName:boxName, parentIndex:parentIndex, n:n, newest:newest, dateKind:dateKind, idKind:idKind, base:base, reads:reads}
end fakeBox

on fakeEvent()
	set fakeEvents to fakeEvents + 1
end fakeEvent

-- A mailbox reference: {account index, mailbox index}; {1, 1} is the unified inbox.
on fakeBoxOf(b)
	return item (item 2 of b) of boxes of item (item 1 of b) of fakeModel
end fakeBoxOf

on fakeAccountIndex(accountId)
	repeat with i from 1 to count fakeModel
		if accountId of item i of fakeModel is accountId then return i
	end repeat
	error "Can't get account." number -1728
end fakeAccountIndex

-- Message `age` (0: newest) of a mailbox: its ID, date and read state.
on fakeId(spec, age)
	if idKind of spec is "burst" then return (base of spec) + ((age * 37) mod 300)
	return (base of spec) + age
end fakeId

on fakeDate(spec, age)
	if dateKind of spec is "thirds" then return fakeT0 - (age div 3)
	if dateKind of spec is "burst" then
		if age < 120 then return fakeT0
		return fakeT0 - (age - 119)
	end if
	return fakeT0 - age
end fakeDate

on fakeAge(spec, messageId)
	if idKind of spec is "burst" then
		repeat with age from 0 to (n of spec) - 1
			if fakeId(spec, age) = messageId then return age
		end repeat
	else
		set age to messageId - (base of spec)
		if age ≥ 0 and age < (n of spec) then return age
	end if
	error "Can't get message." number -1728
end fakeAge

on fakeMessage(b, messageId)
	return {fakeKind:"message", boxRef:b, age:fakeAge(fakeBoxOf(b), messageId), messageId:messageId}
end fakeMessage

on inboxBox()
	return {1, 1}
end inboxBox

on accountName(accountId)
	fakeEvent()
	return accountName of item fakeAccountIndex(accountId) of fakeModel
end accountName

on boxNames(accountId)
	fakeEvent()
	set out to {}
	repeat with spec in boxes of item fakeAccountIndex(accountId) of fakeModel
		set end of out to boxName of spec
	end repeat
	return out
end boxNames

on boxAt(accountId, j)
	return {fakeAccountIndex(accountId), j as integer}
end boxAt

on boxOf(what, b)
	fakeEvent()
	if class of b is record then
		if what is "is mailbox" then return false
		error "Can't get that." number -1728
	end if
	set spec to fakeBoxOf(b)
	if what is "name" then return boxName of spec
	if what is "container" then
		if parentIndex of spec is 0 then return fakeTopLevel
		return {item 1 of b, parentIndex of spec}
	end if
	if what is "is mailbox" then return true
	if what is "account id" then return accountId of item (item 1 of b) of fakeModel
	if what is "account name" then return accountName of item (item 1 of b) of fakeModel
	error "Unknown mailbox property" number -50
end boxOf

on messageIds(b)
	fakeEvent()
	set spec to fakeBoxOf(b)
	set out to {}
	if newest of spec then
		repeat with age from 0 to (n of spec) - 1
			set end of out to fakeId(spec, age)
		end repeat
	else
		repeat with age from (n of spec) - 1 to 0 by -1
			set end of out to fakeId(spec, age)
		end repeat
	end if
	return out
end messageIds

on unreadCount(b)
	fakeEvent()
	set spec to fakeBoxOf(b)
	if reads of spec is "every7" then return ((n of spec) + 6) div 7
	return 0
end unreadCount

on dateById(b, messageId)
	fakeEvent()
	set spec to fakeBoxOf(b)
	return fakeDate(spec, fakeAge(spec, messageId))
end dateById

on readById(b, messageId)
	fakeEvent()
	set spec to fakeBoxOf(b)
	if reads of spec is "every7" then return fakeAge(spec, messageId) mod 7 ≠ 0
	return true
end readById

on messageRef(messageId)
	return fakeMessage(box, messageId)
end messageRef

on refOf(what, r)
	fakeEvent()
	set spec to fakeBoxOf(boxRef of r)
	set messageId to messageId of r
	if what is "date" then return fakeDate(spec, age of r)
	if what is "read" then
		if reads of spec is "every7" then return (age of r) mod 7 ≠ 0
		return true
	end if
	if what is "flagged" then return (age of r) mod 5 = 0
	if what is "subject" then
		if (system attribute "MEEP_MAIL_FAKE") is "hostile" then return fakeHostile(age of r)
		return "Subject " & messageId
	end if
	if what is "sender" then return "Ada <ada@example.com>"
	if what is "mailbox" then return boxRef of r
	error "Unknown message property" number -50
end refOf

-- Texts that would break a naive answer.
on fakeHostile(age)
	set separators to (character id 28) & (character id 29) & (character id 30) & (character id 31)
	if age is 0 then return "a" & separators & "b \"quoted\" " & return & "line" & linefeed & "end +"
	if age is 1 then return "Café 🎉 ✓ 中文 " & separators
	set s to ""
	repeat 500 times
		set s to s & "0123456789"
	end repeat
	return s
end fakeHostile

on messageHeaders(r, limit)
	fakeEvent()
	if (system attribute "MEEP_MAIL_FAKE") is "stall" and age of r is 5 then error "Mail got an error: AppleEvent timed out." number -1712
	set messageId to messageId of r
	if (system attribute "MEEP_MAIL_FAKE") is "hostile" then return {fakeHostile(age of r), {fakeHostile(age of r), missing value}, {"me@example.com", "you@example.com"}}
	return {"m" & messageId & "@example.com", {"Me", missing value}, {"me@example.com", "you@example.com"}}
end messageHeaders
