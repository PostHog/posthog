// Fixed host-owned JXA adapter. Caller data is JSON, never executable source.
ObjC.import('AppKit');
function paste(text) {
  const board = $.NSPasteboard.generalPasteboard;
  const saved = [];
  const items = board.pasteboardItems;
  for (let i = 0; i < items.count; i++) {
    const original = items.objectAtIndex(i), copy = $.NSPasteboardItem.alloc.init;
    const types = original.types;
    for (let j = 0; j < types.count; j++) {
      const type = types.objectAtIndex(j), data = original.dataForType(type);
      if (data) copy.setDataForType(data, type);
    }
    saved.push(copy);
  }
  let read = false;
  // A keystroke returning only means it was queued. Supply text lazily so
  // restoration waits until an application has actually fetched the paste.
  ObjC.registerSubclass({name:'MeepPasteboardText', protocols:['NSPasteboardItemDataProvider'], methods:{
    'pasteboard:item:provideDataForType:': {types:['void',['id','id','id']], implementation:function(board, item, type) {
      item.setStringForType($(text), type); read = true;
    }},
  }});
  const provider = $.MeepPasteboardText.alloc.init, item = $.NSPasteboardItem.alloc.init;
  item.setDataProviderForTypes(provider, $([$.NSPasteboardTypeString]));
  item.setDataForType($.NSData.data, $('org.nspasteboard.TransientType'));
  item.setDataForType($.NSData.data, $('org.nspasteboard.ConcealedType'));
  board.clearContents;
  let owned = board.changeCount;
  try {
    const prepared = board.writeObjects($([item]));
    owned = board.changeCount;
    if (!prepared) throw Error('Could not prepare pasteboard');
    Application('System Events').keystroke('v',{using:'command down'});
    const deadline = Date.now() + 5000;
    while (!read && board.changeCount === owned && Date.now() < deadline) {
      $.NSRunLoop.currentRunLoop.runUntilDate($.NSDate.dateWithTimeIntervalSinceNow(0.01));
    }
    if (!read) throw Error('The target application did not read the paste');
    // Let the pasteboard server finish returning the provided bytes.
    $.NSRunLoop.currentRunLoop.runUntilDate($.NSDate.dateWithTimeIntervalSinceNow(0.1));
  } finally {
    // A person copying something meanwhile owns the new clipboard.
    if (board.changeCount === owned) {
      board.clearContents;
      if (saved.length && !board.writeObjects($(saved))) throw Error('Could not restore pasteboard');
    }
  }
}
function run(argv) {
  const input = $.NSFileHandle.fileHandleWithStandardInput.readDataToEndOfFile;
  const p = JSON.parse(ObjC.unwrap($.NSString.alloc.initWithDataEncoding(input, $.NSUTF8StringEncoding)));
  const app = Application.currentApplication(); app.includeStandardAdditions = true;
  let result = null;
  try {
    switch (p.operation) {
      case 'confirm': {
        const r = app.displayDialog(p.message || '', {withTitle:p.title, buttons:[p.cancelLabel || 'Cancel',p.confirmLabel || 'Continue'], defaultButton:p.confirmLabel || 'Continue', cancelButton:p.cancelLabel || 'Cancel'});
        result = r.buttonReturned === (p.confirmLabel || 'Continue'); break;
      }
      case 'pick': {
        const options = {withPrompt:p.title || 'Choose files', multipleSelectionsAllowed:!!p.multiple};
        if (p.extensions && p.extensions.length) options.ofType = p.extensions;
        const paths = app.chooseFile(options);
        result = (Array.isArray(paths) ? paths : [paths]).map(x => x.toString()); break;
      }
      case 'pickFolder': result = app.chooseFolder({withPrompt:p.title || 'Choose a folder'}).toString(); break;
      case 'save': result = app.chooseFileName({withPrompt:p.title || 'Export',defaultName:p.name || 'Export.txt'}).toString(); break;
      case 'clipboardRead': result = ObjC.unwrap($.NSPasteboard.generalPasteboard.stringForType($.NSPasteboardTypeString)) || ''; break;
      case 'paste': {
        paste(p.text); result = null; break;
      }
      case 'selectedText': {
        const processes = Application('System Events').applicationProcesses.whose({frontmost:true})();
        if (!processes.length) throw Error('No frontmost application');
        const focus = processes[0].attributes.byName('AXFocusedUIElement').value();
        result = focus.attributes.byName('AXSelectedText').value(); break;
      }
      case 'open': {
        const url = $.NSURL.URLWithString($(p.url));
        if (!url || !$.NSWorkspace.sharedWorkspace.openURL(url)) throw Error('No application could open this URL');
        result = null; break;
      }
      case 'calendarCreate': {
        const calendar = Application('Calendar');
        const target = p.calendar ? calendar.calendars.byName(p.calendar) : calendar.calendars()[0];
        if (!target) throw Error('No calendar available');
        const event = calendar.Event({summary:p.title,startDate:new Date(p.start),endDate:new Date(p.end),description:p.notes || '',location:p.location || ''});
        target.events.push(event); result = {id:event.uid()}; break;
      }
      case 'reminderCreate': {
        const reminders = Application('Reminders');
        const list = p.list ? reminders.lists.byName(p.list) : reminders.defaultList();
        const props = {name:p.title,body:p.notes || ''};
        if (p.due) props.dueDate = new Date(p.due);
        const reminder = reminders.Reminder(props); list.reminders.push(reminder);
        result = {id:reminder.id()}; break;
      }
      default: throw Error('Unknown native operation');
    }
    return JSON.stringify({ok:true,value:result});
  } catch (e) {
    if (e.errorNumber === -128) return JSON.stringify({ok:true,value:p.operation === 'confirm' ? false : null});
    return JSON.stringify({ok:false,error:String(e)});
  }
}
