-- Fixed host-owned AppleScript adapter for host.mail's message list
-- (src/mail.rs, `MailApp::messages`). Read-only: it only gets
-- properties, never sets one, and never sends Mail a command. Caller data
-- comes as `argv`, validated by the host first; nothing in it or in a
-- message is evaluated.
--
-- What Mail makes cheap and dear, measured (docs/processes.md): finding a
-- message by index walks the whole mailbox, per message, even inside a range
-- (`messages 1 thru 51` of a 39,000-message mailbox took 3.6 s); the IDs of
-- every message are one event (0.3 s for the same mailbox); a message by ID
-- costs one round trip, about a frame of Mail's main thread. JXA could only
-- address by index, about ten events per message. So:
--
-- - `messages` picks the page from the mailbox's IDs, read once, with a few
--   dates by ID for the order, the cursor and the last second.
-- - `rows` reads given messages by ID. For their fields the reader runs a
--   few at once: the time is in waiting for Mail's next frame, and Mail
--   answers every waiting reader in the same frame.
--
-- Message-ID and recipients come from the message's headers, which Mail may
-- not have downloaded yet: reading them then makes Mail fetch the message
-- while it blocks everything else. So one `rows` reads them, last, with a
-- short timeout per message; after the first that times out it asks for no
-- more, and marks the rest incomplete rather than leaving them out. A page
-- sets Mail fetching one message at most.
--
-- The answer is text: records split by RS (character id 30), fields by US
-- (31), list items by GS (29). Every text from Mail goes through `clean`,
-- which replaces those and FS (28) with spaces and marks it present with "+",
-- so message text can't add a field or a record. `system_mail::parse_plan`
-- and `parse_rows` read it.
--
-- Only the "Mail" section at the end talks to Mail. `system_mail::tests` runs
-- everything above it against a fake of that section, and checks that the
-- section uses only Mail.sdef's read-only terms, as raw codes: Mail is
-- addressed through a variable, so the script compiles without Mail.
global US, RS, GS, box, total, newestFirst, unified, allIds

-- Seconds a message's headers may take before Mail is left alone.
property HEADER_SECONDS : 2

on run argv
	set US to character id 31
	set RS to character id 30
	set GS to character id 29
	try
		openMail()
		if (count argv) > 0 and item 1 of argv is "rows" then return rowsOf(argv)
		return page(argv)
	on error msg number num
		return "err" & US & (num as text) & US & clean(msg)
	end try
end run

-- argv: operation, count, scan, unreadOnly (1/0), before ("y m d seconds" in
-- local time, or ""), the mailbox (account, nth, path joined by US; "" account
-- for the unified inbox), the message `after` (account, nth, Mail ID, path; ""
-- account for none), and the seconds this call may take.
--
-- Answers "ok" and the mailbox for `rows` (account, index in the account's
-- list and name; "" for the unified inbox), then a row per message (`row`).
on page(argv)
	if (count argv) is not 13 then error "Bad mail page request" number -50
	set {op, wanted, scan, unreadOnly, beforeText, boxAccount, boxNth, boxPath, afterAccount, afterNth, afterId, afterPath, budget} to argv
	if op is not "messages" then error "Unknown mail operation" number -50
	set wanted to wanted as integer
	set scan to scan as integer
	set unreadOnly to unreadOnly is "1"
	set budget to budget as integer
	set started to current date
	set unified to boxAccount is ""
	set boxIndex to ""
	set leaf to ""
	set known to missing value
	if unified then
		set box to inboxBox()
	else
		set leaf to last item of split(boxPath)
		set boxIndex to mailboxAt(boxAccount, split(boxPath), boxNth as integer)
		set box to boxAt(boxAccount, boxIndex)
		set known to {boxAccount, accountName(boxAccount), missing value, missing value, boxNth as integer}
	end if
	set allIds to messageIds(box)
	if class of allIds is not list then set allIds to {allIds}
	set total to count allIds
	if total is 0 then return "ok"
	if unreadOnly then
		set unread to unreadCount(box)
		if unread is 0 then return "ok"
	end if
	-- Positions count from the newest end, whichever end that is.
	set newestFirst to true
	if total > 1 then set newestFirst to (dateAt(0) ≥ dateAt(total - 1))

	-- The page continues after `after`, the last message of the previous page:
	-- older ones, and ones from the same second with a lower ID (the reader
	-- orders a page by date, then ID). A plain `before` date takes only
	-- messages older than it.
	set cursor to missing value
	set afterNum to missing value
	if afterAccount is not "" then
		considering case
			set sameBox to afterAccount = boxAccount and afterPath = boxPath and afterNth = boxNth
		end considering
		if sameBox then
			set afterBox to box
		else
			set afterBox to boxAt(afterAccount, mailboxAt(afterAccount, split(afterPath), afterNth as integer))
		end if
		set afterNum to afterId as integer
		set cursor to dateById(afterBox, afterNum)
	else if beforeText is not "" then
		set cursor to localDate(beforeText)
	end if
	-- The first message at or older than the cursor, by bisection over dates.
	set k to 0
	if cursor is not missing value then
		set lo to 0
		set hi to total
		repeat while lo < hi
			set mid to (lo + hi) div 2
			set d to dateAt(mid)
			if d < cursor or (afterNum is not missing value and d = cursor) then
				set hi to mid
			else
				set lo to mid + 1
			end if
		end repeat
		set k to lo
	end if

	-- Which messages make the page. So that its last message is an exact
	-- cursor, the page holds every message newer than the last one's second,
	-- and every message of that second (at most 1000 more); the reader keeps
	-- the highest IDs. Messages skipped as already shown don't count toward
	-- `scan`. An unread page stops once it holds every unread message. A date
	-- is read only where this needs one: the cursor's second and the last.
	set found to {}
	set lastDate to missing value
	set pastCursor to afterNum is missing value
	set looked to 0
	set extra to 0
	set skipped to 0
	repeat with p from k to total - 1
		set m to {msgId:idAt(p), received:missing value}
		if not pastCursor or (count found) ≥ wanted - 1 then set received of m to dateById(box, msgId of m)
		if not pastCursor then set pastCursor to received of m < cursor
		if not pastCursor and msgId of m ≥ afterNum then
			set skipped to skipped + 1
			if skipped > 1000 then exit repeat
		else
			if (count found) ≥ wanted then
				set extra to extra + 1
				if received of m ≠ lastDate or extra > 1000 then exit repeat
			else
				if looked ≥ scan then exit repeat
				set looked to looked + 1
			end if
			set isRead to false
			if unreadOnly then set isRead to readById(box, msgId of m)
			if not isRead then
				if (count found) = wanted - 1 and received of m is missing value then set received of m to dateById(box, msgId of m)
				set end of found to m
				if (count found) = wanted then set lastDate to received of m
				if unreadOnly and k = 0 and skipped = 0 and (count found) ≥ unread and (count found) < wanted then exit repeat
			end if
		end if
		if ((current date) - started) > budget then error "Mail is taking too long" number -1712
	end repeat
	if found is {} then return "ok"

	set out to {joined({"ok", boxAccount, boxIndex as text, leaf}, US)}
	repeat with m in found
		set end of out to row(msgId of m, received of m, missing value, missing value, missing value, missing value, known)
	end repeat
	return joined(out, RS)
end page

-- argv: "rows", the mailbox as `messages` gave it (account, index, name),
-- what to read ("fields", or "headers"), the seconds this call may take, and
-- the messages' Mail IDs joined by US. Answers "ok", then a row per message
-- still there, in the order asked: its fields (`row`), or its ID and headers
-- (`headerFields`).
on rowsOf(argv)
	if (count argv) is not 7 then error "Bad mail rows request" number -50
	set {op, boxAccount, boxIndex, leaf, what, budget, idText} to argv
	set budget to budget as integer
	set started to current date
	set unified to boxAccount is ""
	if unified then
		set box to inboxBox()
	else
		set box to boxAt(boxAccount, boxIndex as integer)
		-- The mailbox list may have changed since `messages` read it.
		considering case
			set sameBox to boxOf("name", box) = leaf
		end considering
		if not sameBox then error "Can't get mailbox." number -1728
	end if
	set out to {"ok"}
	set stalled to false
	set seenKeys to {}
	set seenPlaces to {}
	repeat with idItem in split(idText)
		set messageId to idItem as integer
		set r to messageRef(messageId)
		if what is "fields" then
			set fields to missing value
			try
				set fields to {refOf("date", r), refOf("read", r), refOf("flagged", r), refOf("subject", r), refOf("sender", r), missing value}
			on error number -1728
				-- Gone since `messages` read it.
			end try
			if fields is not missing value then
				if unified then
					set b to refOf("mailbox", r)
					set item 6 of fields to place(b, boxOf("name", b), boxOf("account id", b), seenKeys, seenPlaces)
				end if
				set end of out to row(messageId, item 1 of fields, item 2 of fields, item 3 of fields, item 4 of fields, item 5 of fields, item 6 of fields)
			end if
		else
			if not stalled and ((current date) - started) > budget then set stalled to true
			set head to missing value
			if not stalled then
				try
					set head to messageHeaders(r, HEADER_SECONDS)
				on error number num
					if num is -1712 then set stalled to true
				end try
			end if
			set end of out to numText(messageId) & US & headerFields(head)
		end if
	end repeat
	return joined(out, RS)
end rowsOf

-- One message's fields but its headers: ID, date, read, flagged, subject,
-- sender, its mailbox (account ID, account name, name, path, nth). Unknown
-- ones are "".
on row(messageId, received, isRead, isFlagged, subject, sender, home)
	if home is missing value then set home to {missing value, missing value, missing value, missing value, missing value}
	set fields to {numText(messageId), dateText(received), flag(isRead), flag(isFlagged), clean(subject), clean(sender), ¬
		clean(item 1 of home), clean(item 2 of home), clean(item 3 of home), cleanList(item 4 of home), numText(item 5 of home)}
	return joined(fields, US)
end row

-- Headers as fields: Message-ID, To names, To addresses, and "1" when they
-- weren't read.
on headerFields(head)
	if head is missing value then return joined({"", "", "", "1"}, US)
	return joined({clean(item 1 of head), cleanList(item 2 of head), cleanList(item 3 of head), "0"}, US)
end headerFields

-- For the unified inbox, a message's own mailbox: {account ID, account name,
-- mailbox name, path, 0}, remembered in `seenKeys` and `seenPlaces`.
on place(b, boxName, accountId, seenKeys, seenPlaces)
	set boxKey to accountId & US & boxName
	considering case
		repeat with j from 1 to count seenKeys
			if item j of seenKeys = boxKey then return item j of seenPlaces
		end repeat
	end considering
	set home to {accountId, boxOf("account name", b), boxName, pathOf(b, boxName), 0}
	set end of seenKeys to boxKey
	set end of seenPlaces to home
	return home
end place

-- The ID at position `p` (from the newest end), and its date.
on idAt(p)
	if newestFirst then return item (p + 1) of my allIds
	return item (total - p) of my allIds
end idAt

on dateAt(p)
	return dateById(box, idAt(p))
end dateAt

-- The names from the account down to `b`, `leaf` last. A mailbox's `name`
-- is its own name only; the path is read up its containers, which stops at
-- the top: no container, or one that isn't a mailbox (the account).
on pathOf(b, leaf)
	set names to {leaf}
	set cur to b
	repeat 8 times
		-- No container, an error or no answer at all: the top.
		try
			set upper to missing value
			set upper to boxOf("container", cur)
			if upper is missing value then exit repeat
			set isBox to boxOf("is mailbox", upper)
			set upName to boxOf("name", upper)
		on error
			exit repeat
		end try
		if not isBox then exit repeat
		if upName is missing value or upName is "" then exit repeat
		set beginning of names to upName
		set cur to upper
	end repeat
	return names
end pathOf

-- Where the `nth` (from 0) mailbox at `path` is in an account's mailbox list.
-- Mail's by-name lookup misses some mailboxes (Gmail's Important, All Mail,
-- labels), and Mail may not name a nested mailbox's container, so two can
-- share a path: the list is matched by name, then path, then position.
on mailboxAt(accountId, path, nth)
	set names to boxNames(accountId)
	set leaf to last item of path
	set seen to 0
	repeat with j from 1 to count names
		if j > 500 then exit repeat
		considering case
			set isNamed to (item j of names) = leaf
		end considering
		if isNamed then
			considering case
				set samePath to pathOf(boxAt(accountId, j), leaf) = path
			end considering
			if samePath then
				if seen = nth then return j
				set seen to seen + 1
			end if
		end if
	end repeat
	error "Can't get mailbox." number -1728
end mailboxAt

on split(s)
	set AppleScript's text item delimiters to US
	set parts to text items of s
	set AppleScript's text item delimiters to ""
	return parts
end split

on joined(xs, sep)
	set AppleScript's text item delimiters to sep
	set s to xs as text
	set AppleScript's text item delimiters to ""
	return s
end joined

-- "y m d seconds" in local time, as a date.
on localDate(s)
	set {y, m, d, t} to words of s
	set x to current date
	set day of x to 1
	set year of x to y as integer
	set month of x to m as integer
	set day of x to d as integer
	set time of x to t as integer
	return x
end localDate

on dateText(d)
	if class of d is not date then return ""
	return (year of d as text) & " " & ((month of d) as integer) & " " & day of d & " " & time of d
end dateText

on flag(b)
	if b is true then return "1"
	if b is false then return "0"
	return ""
end flag

-- A whole number as digits, even past AppleScript's integer range; "" for none.
on numText(x)
	if x is missing value then return ""
	if class of x is integer then return x as text
	set hi to x div 1000000
	set lo to (x mod 1000000) div 1
	return (hi as text) & text -6 thru -1 of ("000000" & lo)
end numText

-- Text from Mail, marked present with "+", the separators replaced; "" for none.
on clean(v)
	if v is missing value then return ""
	set s to v as text
	set AppleScript's text item delimiters to {US, RS, GS, character id 28}
	set parts to text items of s
	set AppleScript's text item delimiters to " "
	set s to parts as text
	set AppleScript's text item delimiters to ""
	return "+" & s
end clean

-- A list: "" for none, else how many items (at most 10), then each item
-- cleaned, all split by GS.
on cleanList(xs)
	if xs is missing value then return ""
	if class of xs is not list then set xs to {xs}
	set out to {}
	repeat with x in xs
		if (count out) ≥ 10 then exit repeat
		set end of out to clean(contents of x)
	end repeat
	return joined({(count out) as text} & out, GS)
end cleanList

-- Mail -----------------------------------------------------------------------
-- Everything that talks to Mail, and only reads. `mailApp` is set once Mail is
-- known to be running: addressing a Mail that isn't would launch it.
global mailApp

on openMail()
	if not (application id "com.apple.mail" is running) then error "Mail is not running" number -600
	set mailApp to application id "com.apple.mail"
end openMail

on inboxBox()
	tell mailApp to return a reference to «property inmb»
end inboxBox

on accountName(accountId)
	tell mailApp to return name of «class mact» id accountId
end accountName

on boxNames(accountId)
	tell mailApp to return name of every «class mbxp» of «class mact» id accountId
end boxNames

on boxAt(accountId, j)
	tell mailApp to return a reference to «class mbxp» j of «class mact» id accountId
end boxAt

-- A mailbox's name, container, whether it is a mailbox (not an account), or
-- its account's ID or name.
on boxOf(what, b)
	tell mailApp
		if what is "name" then return name of b
		if what is "container" then return (get «property mbxc» of b)
		if what is "is mailbox" then set boxKind to class of b
		if what is "account id" then return id of «property mact» of b
		if what is "account name" then return name of «property mact» of b
	end tell
	if what is "is mailbox" then return boxKind is «class mbxp» or boxKind is «class mbxc»
	error "Unknown mailbox property" number -50
end boxOf

-- The IDs of every message, in Mail's order: one event, integers only.
on messageIds(b)
	tell mailApp to return id of every «class mssg» of b
end messageIds

on unreadCount(b)
	tell mailApp to return «property mbuc» of b
end unreadCount

on dateById(b, messageId)
	tell mailApp to return «property rdrc» of «class mssg» id messageId of b
end dateById

on readById(b, messageId)
	tell mailApp to return «property isrd» of «class mssg» id messageId of b
end readById

on messageRef(messageId)
	tell mailApp to return a reference to «class mssg» id messageId of box
end messageRef

-- One property of the message `r` refers to.
on refOf(what, r)
	tell mailApp
		if what is "date" then return «property rdrc» of r
		if what is "read" then return «property isrd» of r
		if what is "flagged" then return «property isfl» of r
		if what is "subject" then return «property subj» of r
		if what is "sender" then return «property sndr» of r
		if what is "mailbox" then return «property mbxp» of r
	end tell
	error "Unknown message property" number -50
end refOf

-- {Message-ID, To names, To addresses}, waiting at most `limit` seconds.
on messageHeaders(r, limit)
	with timeout of limit seconds
		tell mailApp
			set header to «property meid» of r
			set people to «property pALL» of every «class trcp» of r
		end tell
	end timeout
	set names to {}
	set addresses to {}
	repeat with person in people
		set {who, address} to {missing value, missing value}
		try
			set who to name of person
		end try
		try
			set address to «property radd» of person
		end try
		set end of names to who
		set end of addresses to address
	end repeat
	return {header, names, addresses}
end messageHeaders
