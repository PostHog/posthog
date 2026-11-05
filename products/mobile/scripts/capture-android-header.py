from pathlib import Path
import subprocess
import sys
import time
import xml.etree.ElementTree as ET


output = Path(sys.argv[1])


def adb(*args: str) -> bytes:
    return subprocess.check_output(['adb', '-s', 'emulator-5554', *args])


def find(identifier: str) -> ET.Element:
    deadline = time.monotonic() + 40
    while time.monotonic() < deadline:
        adb('shell', 'uiautomator', 'dump', '/sdcard/header-window.xml')
        xml = adb('exec-out', 'cat', '/sdcard/header-window.xml')
        (output / 'window.xml').write_bytes(xml)
        root = ET.fromstring(xml)
        for node in root.iter('node'):
            if node.get('resource-id', '').split('/')[-1] == identifier:
                return node
        time.sleep(1)
    (output / 'failure.png').write_bytes(adb('exec-out', 'screencap', '-p'))
    raise RuntimeError(f'Element did not appear: {identifier}')


def tap(identifier: str) -> None:
    import re

    node = find(identifier)
    left, top, right, bottom = map(int, re.findall(r'\d+', node.attrib['bounds']))
    adb('shell', 'input', 'tap', str((left + right) // 2), str((top + bottom) // 2))


def capture(prefix: str) -> None:
    import re

    size = adb('shell', 'wm', 'size').decode()
    width, height = map(int, re.findall(r'(\d+)x(\d+)', size)[-1])
    time.sleep(1)
    (output / f'{prefix}-initial.png').write_bytes(adb('exec-out', 'screencap', '-p'))
    for index in range(1, 4):
        adb('shell', 'input', 'swipe', str(width // 2), str(int(height * .65)), str(width // 2), str(int(height * .59)), '1000')
        time.sleep(1)
        (output / f'{prefix}-scroll-{index}.png').write_bytes(adb('exec-out', 'screencap', '-p'))


adb('shell', 'cmd', 'uimode', 'night', 'no')
adb('shell', 'settings', 'put', 'system', 'font_scale', '1.0')
adb('shell', 'am', 'start', '-n', 'com.posthog.mobile/.MainActivity')
tap('try-demo')
tap('inbox-row-demo-report-load-time')
find('report-scroll')
capture('report')
adb('shell', 'am', 'start', '-W', '-a', 'android.intent.action.VIEW', '-d', 'posthog://report/demo-report-load-time/details', 'com.posthog.mobile')
find('report-details-scroll')
capture('details')
