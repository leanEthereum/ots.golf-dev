#!/usr/bin/env python3
"""Optional Firefox UI audit of the seeded, running localhost preview.

Start service/run-local.sh first; this runner reads the site and exercises browser controls.
It never seeds the database, submits a proof, contacts GitHub APIs, pushes or deploys.
Requires Firefox and Python's standard library; screenshots remain in --output-dir.
Firefox profiles and logs are temporary and are removed on exit.

    python3 service/browser_check.py
    python3 service/browser_check.py --base-url http://127.0.0.1:8000 --output-dir /tmp/ots-ui
"""
from __future__ import annotations

import argparse
import base64
from contextlib import contextmanager
import ipaddress
import json
import os
from pathlib import Path
import re
import shutil
import socket
import subprocess
import tempfile
import time
from urllib.parse import urlsplit


ROOT = Path(__file__).resolve().parents[1]


def local_url(value: str) -> str:
    try:
        parsed = urlsplit(value)
        host = parsed.hostname or ''
        _ = parsed.port  # Validate malformed/non-numeric ports.
        loopback = host.lower() == 'localhost' or ipaddress.ip_address(host).is_loopback
    except ValueError:
        loopback = False
    if not loopback or parsed.scheme not in ('http', 'https') or parsed.username or parsed.password:
        raise argparse.ArgumentTypeError('Use an http(s) loopback URL, such as http://127.0.0.1:8000.')
    if parsed.path not in ('', '/') or parsed.query or parsed.fragment:
        raise argparse.ArgumentTypeError('--base-url must name the site root without a query or fragment.')
    return value.rstrip('/')


def free_port() -> int:
    with socket.socket() as probe:
        probe.bind(('127.0.0.1', 0))
        return probe.getsockname()[1]


class Marionette:
    def __init__(self, connection: socket.socket):
        self.socket = connection
        self.serial = 0

    def read(self):
        prefix = bytearray()
        while True:
            char = self.socket.recv(1)
            if not char:
                raise RuntimeError('Firefox closed the Marionette connection.')
            if char == b':':
                break
            if not char.isdigit() or len(prefix) >= 9:
                raise RuntimeError('Invalid Marionette packet length.')
            prefix.extend(char)
        size = int(prefix or b'0')
        if not 0 < size <= 64 * 1024 * 1024:
            raise RuntimeError('Marionette packet length is outside the permitted range.')
        body = bytearray()
        while len(body) < size:
            chunk = self.socket.recv(min(size - len(body), 65536))
            if not chunk:
                raise RuntimeError('Firefox disconnected during a Marionette response.')
            body.extend(chunk)
        return json.loads(body)

    def command(self, name: str, params=None):
        self.serial += 1
        payload = json.dumps([0, self.serial, name, params or {}]).encode()
        self.socket.sendall(str(len(payload)).encode() + b':' + payload)
        response = self.read()
        if not isinstance(response, list) or len(response) != 4 or response[1] != self.serial:
            raise RuntimeError(f'Unexpected Marionette response: {response!r}')
        if response[2]:
            raise RuntimeError(response[2])
        return response[3]

    def js(self, script: str):
        result = self.command('WebDriver:ExecuteScript', {
            'script': script, 'args': [], 'newSandbox': True, 'sandbox': 'default'})
        return result.get('value', result)


@contextmanager
def firefox_session(binary: str, port: int, *, reduced_motion: bool = True):
    with tempfile.TemporaryDirectory(prefix='ots-firefox-') as directory:
        profile = Path(directory) / 'profile'
        profile.mkdir()
        prefs = {
            'marionette.port': port,
            'ui.prefersReducedMotion': int(reduced_motion),
            'browser.shell.checkDefaultBrowser': False,
            'datareporting.policy.dataSubmissionEnabled': False,
            'toolkit.telemetry.enabled': False,
            'browser.startup.homepage_override.mstone': 'ignore',
            'network.proxy.type': 0,
        }
        (profile / 'user.js').write_text(''.join(
            f'user_pref({json.dumps(key)}, {json.dumps(value)});\n' for key, value in prefs.items()))
        log_path = Path(directory) / 'firefox.log'
        with log_path.open('w') as log:
            process = subprocess.Popen(
                [binary, '--headless', '--no-remote', '--profile', str(profile), '--marionette'],
                stdout=log, stderr=log, env={**os.environ, 'MOZ_HEADLESS': '1'})
            connection = None
            browser = None
            started = False
            try:
                deadline = time.monotonic() + 25
                while time.monotonic() < deadline:
                    try:
                        connection = socket.create_connection(('127.0.0.1', port), timeout=1)
                        connection.settimeout(25)
                        break
                    except OSError:
                        if process.poll() is not None:
                            raise RuntimeError(f'Firefox exited during startup:\n{log_path.read_text()}')
                        time.sleep(.25)
                if connection is None:
                    raise RuntimeError(f'Firefox did not start:\n{log_path.read_text()}')
                browser = Marionette(connection)
                browser.read()  # Protocol handshake.
                session = browser.command('WebDriver:NewSession', {
                    'capabilities': {'alwaysMatch': {'acceptInsecureCerts': False}}})
                started = True
                print('Firefox', session['capabilities']['browserVersion'])
                yield browser
            finally:
                if browser and started:
                    try:
                        browser.command('WebDriver:DeleteSession')
                    except (OSError, RuntimeError, ValueError):
                        pass
                if connection:
                    connection.close()
                if process.poll() is None:
                    process.terminate()
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=10)


def demo_best(config: dict, slug: str) -> int:
    """The best demo record of a track: the claim its seeded board shows."""
    fixtures = json.loads((ROOT / 'service/demo/submissions.json').read_text())['submissions']
    track = next(t for t in config['tracks'] if t['slug'] == slug)
    claims = [r['claim'] for r in fixtures if r['track'] == slug and r['is_record']]
    return max(claims) if track['direction'] == '+' else min(claims)


def assert_rules_have_no_scores(text: str, config: dict) -> None:
    claims = {demo_best(config, track['slug']) for track in config['tracks']}
    # Every current claim is checked in score-bearing prose. Small numbers also occur
    # legitimately in fractions, section numbers and fixed contract parameters.
    for claim in claims:
        number = rf'(?<![\w,/]){claim}(?![\w,/])'
        assert not re.search(rf'(?:score|record|candidate|bound)\s+(?:(?:of|is|:|=)\s*)?{number}\b|'
                             rf'{number}\s+compressions?\b', text, re.I), f'Rules publish score {claim}'
    legitimate = {0, 1, 2, 3, 4, 21, 41, 42, 127, 128, 256, 512, 1048576, 5248, 5376, 5504}
    for claim in claims - legitimate:
        assert not re.search(rf'\b{claim}\b', text), f'Rules publish score {claim}'


def audit(browser: Marionette, base_url: str, output: Path, config: dict) -> None:
    command, js = browser.command, browser.js
    slugs = {t['slug'] for t in config['tracks']}
    upper_admitted = [t for t in config.get('upper_tracks', []) if t in slugs]
    riscv_enabled = 'upper-riscv' in upper_admitted
    leanisa_enabled = 'upper-leanisa' in upper_admitted
    # One board per admitted upper track, plus the lower board and the progress table.
    lb_tables = len(upper_admitted) + 2
    # A track with no seeded record draws no chart series, so `upper-leanisa` adds a board and a
    # chart panel but no line until someone submits.
    seeded = {r['track'] for r in
              json.loads((ROOT / 'service/demo/submissions.json').read_text())['submissions']}
    upper_series = len([t for t in upper_admitted if t in seeded])
    command('WebDriver:SetWindowRect', {'width': 1360, 'height': 1700})
    command('WebDriver:Navigate', {'url': base_url + '/'})
    print('Home:', js('return {title: document.title, cards: document.querySelectorAll(".framework-card").length, lowerSeries: document.querySelectorAll(".chart-series[data-kind=lower]").length, tables: document.querySelectorAll(".lb-table").length, width: innerWidth, scrollWidth: document.documentElement.scrollWidth};'))
    assert js('return document.querySelectorAll(".chart-series[data-kind=lower]").length === 1;')
    assert js(f'return document.querySelectorAll(".lb-table").length === {lb_tables};')
    assert js('return document.querySelector(".upper-card").getBoundingClientRect().bottom <= document.querySelector(".framework-cards").getBoundingClientRect().top;')
    assert js('return document.querySelector("#upper-compressions-title").textContent.trim() === "By compressions" && getComputedStyle(document.querySelector(".chart-series[data-kind=upper] .line")).strokeDasharray === "none";')
    assert js('return document.querySelector("#framework-generality-1 .framework-generality").textContent === "Whole-word DAGs";')
    assert js('return [...document.querySelectorAll("header.top nav a")].map(a => a.textContent.trim()).join(",") === "Rules,Hall of Fame";')
    assert js('return !document.querySelector(".board-track[data-track=lower]").innerText.includes("Admission pending");')
    assert js('return !document.querySelector("main").innerText.includes("Lower submissions open");')
    lower_claim = demo_best(config, 'lower-generality-1')
    expected_label = json.dumps(f"Whole-word lower · {lower_claim}")
    assert js('return document.querySelector(".chart-series[data-series=lower-generality-1]").dataset.status === "certified" && document.querySelector(".chart-series[data-series=lower-generality-1] .label").textContent === ' + expected_label + ';')
    assert js('return document.querySelectorAll(".framework-overview .upper-score strong").length >= 1 && document.querySelectorAll(".framework-overview .tag").length >= 3;'), 'This check requires the seeded local preview (service/run-local.sh).'

    assert js('return !document.querySelector(".board-track[data-track=upper]").hidden && document.querySelector(".board-track[data-track=lower]").hidden && document.querySelector(".seg-btn").dataset.track === "upper";')
    js('document.querySelector(".seg-btn[data-track=upper]").click(); return true;')
    assert js('return !document.querySelector(".board-track[data-track=upper]").hidden && document.querySelector(".board-track[data-track=lower]").hidden && location.hash === "#upper";')
    assert js('return document.querySelector(".lower-switch") === null;')
    upper_claim = demo_best(config, 'upper-compressions')
    upper_scores = js('return [...document.querySelectorAll(".lb-table[data-track=upper-compressions] .lb-row")].map(r => Number(r.dataset.score));')
    assert min(upper_scores) == upper_claim and upper_scores == sorted(upper_scores), upper_scores
    js('document.querySelector(".lb-table[data-track=upper-compressions] .sort-btn[data-key=score]").click(); return true;')
    assert js('return document.querySelector(".lb-table[data-track=upper-compressions] th[aria-sort=descending]") !== null;')
    js('document.querySelector(".chart-series[data-kind=upper] .chart-record").focus(); return true;')
    assert js('return !document.querySelector(".tooltip").hidden && document.querySelector(".tooltip").textContent.includes("Upper bound") && document.querySelector(".tooltip").textContent.includes("demo");')
    js('document.activeElement.blur(); return true;')
    js('document.querySelector(".seg-btn[data-track=lower]").click(); return true;')
    js('document.querySelector(".lb-table[data-track=lower-generality-1] .sort-btn[data-key=score]").click(); return true;')
    scores = js('return [...document.querySelectorAll(".lb-table[data-track=lower-generality-1] .lb-row")].map(r => Number(r.dataset.score));')
    assert scores == sorted(scores), scores
    js('document.querySelector(".chart-record").focus(); return true;')
    assert js('return !document.querySelector(".tooltip").hidden;')
    js('document.activeElement.blur(); window.scrollTo(0, 0); return true;')
    (output / 'home-desktop.png').write_bytes(base64.b64decode(command('WebDriver:TakeScreenshot', {'full': True})['value']))
    assert js(f'return document.querySelectorAll(".chart-series[data-kind=upper]").length === {upper_series} && document.querySelector(".chart-series[data-kind=upper]").dataset.series === "upper-compressions" && document.querySelector(".chart-series[data-kind=upper]").dataset.status === "certified";')
    if riscv_enabled:
        riscv_claim = demo_best(config, 'upper-riscv')
        assert min(js('return [...document.querySelectorAll(".lb-table[data-track=upper-riscv] .lb-row")].map(r => Number(r.dataset.score));')) == riscv_claim
        assert js('return JSON.parse(document.getElementById("chart-points").textContent).every(p => p.unit.startsWith("compression")) && JSON.parse(document.getElementById("upper-riscv-chart-points").textContent).every(p => p.unit === "cycles");')
        assert js('return document.querySelector(".upper-riscv-dashboard").hidden && !document.querySelector(".chart-panel[data-chart=compressions]").hidden;')
        js('document.querySelector(".chart-btn[data-chart=upper-riscv]").click(); return true;')
        assert js('return !document.querySelector(".upper-riscv-dashboard").hidden && document.querySelector(".chart-panel[data-chart=compressions]").hidden;')
        js('document.querySelector(".upper-riscv-dashboard .chart-record").focus(); return true;')
        assert js('return !document.querySelector(".upper-riscv-dashboard .tooltip").hidden && document.querySelector(".upper-riscv-dashboard .tooltip").textContent.includes("cycles");')
        js('document.activeElement.blur(); return true;')
        (output / 'riscv-chart.png').write_bytes(base64.b64decode(command('WebDriver:TakeScreenshot', {'full': False})['value']))
        js('document.querySelector(".chart-btn[data-chart=compressions]").click(); return true;')
    if leanisa_enabled:
        # No demo rows exist for this track, so the board is the empty presentation.
        assert js('return document.querySelector(".upper-leanisa-card") !== null;')
        assert js('return document.querySelector(".upper-leanisa-card .no-record") !== null;')
        # The public-input surcharge is stated wherever the score is, and spans the card.
        note = js('return (() => { const n = document.querySelector(".upper-leanisa-card '
                  '.upper-card-note"); if (!n) return null; const c = n.closest(".upper-card"); '
                  'return {text: n.textContent, wide: n.getBoundingClientRect().width > '
                  '0.8 * c.getBoundingClientRect().width}; })();')
        assert note and '120 cycles' in note['text'], note
        assert note['wide'], 'the cost note must span the card, not sit in the narrow column'
        # A third chart tab and a third leaderboard panel, driven by the same generic JS.
        js('document.querySelector(".chart-btn[data-chart=upper-leanisa]").click(); return true;')
        assert js('return !document.querySelector(".upper-leanisa-dashboard").hidden && '
                  'document.querySelector(".chart-panel[data-chart=compressions]").hidden;')
        js('document.querySelector(".chart-btn[data-chart=compressions]").click(); return true;')
        js('document.querySelector(".seg-btn[data-track=upper]").click(); '
           'document.querySelector(".upper-btn[data-upper=upper-leanisa]").click(); return true;')
        assert js('return !document.querySelector(".upper-board[data-upper=upper-leanisa]").hidden'
                  ' && document.querySelector(".upper-board[data-upper=upper-compressions]").hidden;')
        js('document.querySelector(".upper-btn[data-upper=upper-compressions]").click(); '
           'document.querySelector(".seg-btn[data-track=lower]").click(); '
           'document.querySelector(".seg-btn[data-track=upper]").click(); return true;')
    js('document.documentElement.dataset.theme = "light"; document.getElementById("dash-title").scrollIntoView(); return true;')
    (output / 'chart-light.png').write_bytes(base64.b64decode(command('WebDriver:TakeScreenshot', {'full': False})['value']))
    print('Desktop chart, direction toggle, sorting, and keyboard tooltip passed')
    command('WebDriver:Navigate', {'url': base_url + '/?framework=generality-1#upper'})
    assert js(f'return document.querySelectorAll(".lb-table").length === {lb_tables} && document.querySelectorAll(".chart-series[data-kind=lower]").length === 1 && !document.querySelector(".board-track[data-track=upper]").hidden && !document.querySelector(".framework-board[data-framework=generality-1]").hidden;')
    command('WebDriver:Navigate', {'url': base_url + '/rules'})
    assert js('return document.querySelectorAll(".rules-diagram svg[role=img]").length === 1;')
    assert js('return document.querySelectorAll("details[open]").length === 0;')
    assert js('return document.querySelector("summary").textContent === "What is a one-time signature?";')
    assert js('return [...document.querySelectorAll("main p, main table, main figure, main ol, main ul")].every(e => e.closest("details") || e.parentElement.tagName === "MAIN");')
    js('document.querySelector("#ots summary").focus(); return true;')
    enter = {'actions': [{'type': 'key', 'id': 'keyboard', 'actions': [
        {'type': 'keyDown', 'value': '\ue007'}, {'type': 'keyUp', 'value': '\ue007'}]}]}
    command('WebDriver:PerformActions', enter)
    assert js('return document.querySelector("#ots").open;')
    command('WebDriver:PerformActions', enter)
    assert js('return !document.querySelector("#ots").open;')
    print('Rules summary words:', js(r'return document.querySelector("main").innerText.trim().split(/\s+/).length;'))
    (output / 'rules-summary.png').write_bytes(base64.b64decode(command('WebDriver:TakeScreenshot', {'full': True})['value']))
    js('document.documentElement.dataset.theme = "light"; return true;')
    for anchor in ('generic-admissibility', 'generic-algorithms', 'upper-compressions', 'cut',
                   'whole-word-model', 'whole-words', 'submission-format',
                   'limits', 'legacy-certificates', 'model', 'params', 'hash', 'security'):
        command('WebDriver:Navigate', {'url': base_url + '/rules#' + anchor})
        assert js('return document.querySelector("#' + anchor + '").closest("details").open;')
    js('document.querySelectorAll("details").forEach(d => d.open = true); return true;')
    assert js('return [...document.querySelectorAll(".rules-diagram svg")].every(s => document.getElementById(s.getAttribute("aria-labelledby").split(" ")[0]));')
    assert js('return document.querySelector("#cut").closest("details").open;')
    assert_rules_have_no_scores(js('return document.querySelector("main").innerText;'), config)
    print('Rules visible words:', js(r'return document.querySelector("main").innerText.trim().split(/\s+/).length;'))
    js('window.scrollTo(0, 0); return true;')
    (output / 'rules-expanded.png').write_bytes(base64.b64decode(command('WebDriver:TakeScreenshot', {'full': True})['value']))
    command('WebDriver:Navigate', {'url': base_url + '/'})
    command('WebDriver:SetWindowRect', {'width': 390, 'height': 844})
    print('Narrow layout:', js('return {width: innerWidth, scrollWidth: document.documentElement.scrollWidth, chartWidth: document.querySelector(".chart-plot").clientWidth, chartScroll: document.querySelector(".chart-plot").scrollWidth};'))
    assert js('return document.documentElement.scrollWidth <= innerWidth;')
    assert js('return document.querySelector(".chart-plot").scrollWidth > document.querySelector(".chart-plot").clientWidth;')
    (output / 'home-narrow.png').write_bytes(base64.b64decode(command('WebDriver:TakeScreenshot', {'full': True})['value']))
    command('WebDriver:Navigate', {'url': base_url + '/rules'})
    assert js('return document.documentElement.scrollWidth <= innerWidth;')
    assert js('return document.querySelectorAll("details[open]").length === 0;')
    (output / 'rules-narrow.png').write_bytes(base64.b64decode(command('WebDriver:TakeScreenshot', {'full': True})['value']))
    js('document.querySelectorAll("details").forEach(d => d.open = true); return true;')
    assert js('return document.documentElement.scrollWidth <= innerWidth;')
    assert js('return [...document.querySelectorAll(".rules-diagram-scroll")].every(d => d.scrollWidth > d.clientWidth);')
    print('Filtered deep link, rules expansion, diagrams, and mobile overflow checks passed')
    # Audit actual phone widths in a same-origin viewport; Firefox's desktop window stops at 500px.
    for width in (320, 390):
        for path in ('/', '/rules'):
            js("var testFrame = document.createElement('iframe'); testFrame.id = 'test-frame'; testFrame.style.cssText = 'width:" + str(width) + "px;height:844px;border:0'; fetch('" + path + "').then(r=>r.text()).then(html=>testFrame.srcdoc=html); document.body.replaceChildren(testFrame); return true;")
            ready = False
            for _ in range(40):
                if js("return document.getElementById('test-frame').contentDocument.readyState === 'complete' && document.getElementById('test-frame').contentDocument.querySelector('main') !== null;"):
                    ready = True
                    break
                time.sleep(.1)
            assert ready, f'Phone viewport did not load {path}'
            viewport = js("return {width: document.getElementById('test-frame').contentWindow.innerWidth, scroll: document.getElementById('test-frame').contentDocument.documentElement.scrollWidth};")
            assert viewport['width'] == width and viewport['scroll'] <= width, (path, viewport)
            print('Phone viewport:', path, viewport)
            if path == '/rules':
                assert js("return document.getElementById('test-frame').contentDocument.querySelectorAll('details[open]').length === 0;")
                js("document.getElementById('test-frame').contentDocument.querySelectorAll('details').forEach(d => d.open = true); return true;")
                assert js("return document.getElementById('test-frame').contentDocument.documentElement.scrollWidth <= " + str(width) + ";")
    command('WebDriver:SetWindowRect', {'width': 1360, 'height': 1700})
    command('WebDriver:Navigate', {'url': base_url + '/'})
    assert js("return matchMedia('(prefers-reduced-motion: reduce)').matches;")
    time.sleep(.5)  # Let the initial intersection observer settle the reduced-motion drawing.
    before = js("return [...document.querySelectorAll('.scheme-art [data-r]')].map(e => e.getAttribute('class')).join('|');")
    time.sleep(8.5)
    after = js("return [...document.querySelectorAll('.scheme-art [data-r]')].map(e => e.getAttribute('class')).join('|');")
    assert before == after
    assert js("return getComputedStyle(document.querySelector('.scheme-art .n')).transitionDuration === '0s';")
    for mode in ('dark', 'light'):
        js("document.documentElement.dataset.theme = '" + mode + "'; return true;")
        (output / ('home-' + mode + '.png')).write_bytes(base64.b64decode(command('WebDriver:TakeScreenshot', {'full': True})['value']))
    js("document.querySelector('.chart-record').focus(); return true;")
    assert js("return !document.querySelector('.tooltip').hidden;")
    assert js("const t = document.querySelector('.tooltip').getBoundingClientRect(), f = document.querySelector('.chart').getBoundingClientRect(); return t.left >= f.left && t.right <= f.right && t.top >= f.top;")
    js("document.dispatchEvent(new KeyboardEvent('keydown', {key: 'Escape', bubbles: true})); return true;")
    assert js("return document.querySelector('.tooltip').hidden;")
    js("const c = document.querySelector('.chart-record circle').getBoundingClientRect(); document.querySelector('.record-chart').dispatchEvent(new PointerEvent('pointermove', {clientX:c.x+c.width/2,clientY:c.y+c.height/2,pointerType:'mouse',bubbles:true})); return true;")
    assert js("return !document.querySelector('.tooltip').hidden;")
    js("document.dispatchEvent(new KeyboardEvent('keydown', {key: 'Escape', bubbles: true})); return true;")
    assert js("return document.querySelector('.tooltip').hidden;")
    js("document.querySelector('.chart-record').blur(); document.querySelector('.chart-record').focus(); document.querySelector('.chart-plot').dispatchEvent(new Event('scroll')); return true;")
    assert js("return document.querySelector('.tooltip').hidden;")
    command('WebDriver:Navigate', {'url': base_url + '/rules#%E0%A4%A'})
    assert js("return document.querySelector('h1').textContent === 'Rules';")
    command('WebDriver:Navigate', {'url': base_url + '/no-such-page'})
    assert js("return document.querySelector('main h1') !== null;")
    print('Light/dark, reduced motion, phone widths, tooltip Escape/scroll and HTML 404 checks passed')


def audit_eye_motion(browser: Marionette, base_url: str) -> None:
    browser.command('WebDriver:Navigate', {'url': base_url + '/'})
    assert not browser.js("return matchMedia('(prefers-reduced-motion: reduce)').matches;")
    assert browser.js("return document.querySelectorAll('.scheme-art [data-r=bead]').length === 810;")
    browser.js("""
        const svg = document.querySelector('.scheme-art');
        const started = performance.now();
        const status = () => [...svg.querySelectorAll('[data-r]')].map(e =>
            ['revealed', 'recomputed', 'untouched'].find(c => e.classList.contains(c))).join('');
        const audit = {closings: [], opens: [], changes: 0, changesWhileOpen: 0, unlitAtClose: 0, rootDark: 0};
        let pattern = status(), eye = svg.dataset.eye;
        svg.dataset.motionAudit = JSON.stringify(audit);
        new MutationObserver(changes => {
            if (changes.some(c => c.attributeName === 'class')) {
                const now = status();
                if (now !== pattern) { audit.changes++; if (svg.dataset.eye !== 'closed') audit.changesWhileOpen++; pattern = now; }
            }
            if (svg.dataset.eye !== eye) {
                eye = svg.dataset.eye;
                const t = performance.now() - started;
                if (eye === 'closing') {
                    audit.closings.push(t);
                    audit.unlitAtClose += svg.querySelectorAll('.wait').length;
                    if (+svg.querySelector('[data-root-glow]').getAttribute('opacity') < .5) audit.rootDark++;
                }
                if (eye === 'open') audit.opens.push(t);
            }
            svg.dataset.motionAudit = JSON.stringify(audit);
        }).observe(svg, {subtree: true, attributes: true, attributeFilter: ['class', 'data-eye']});
        return true;
    """)
    deadline = time.monotonic() + 40
    while time.monotonic() < deadline:
        time.sleep(.25)
        if browser.js("return JSON.parse(document.querySelector('.scheme-art').dataset.motionAudit).opens.length >= 3;"):
            break
    result = browser.js("return JSON.parse(document.querySelector('.scheme-art').dataset.motionAudit);")
    assert len(result['opens']) >= 3 and result['changes'] == len(result['closings']) >= 2, result
    assert all(5000 <= b - a <= 12000 for a, b in zip(result['opens'], result['opens'][1:])), result
    assert result['changesWhileOpen'] == 0 and result['unlitAtClose'] == 0 and result['rootDark'] == 0, result
    assert browser.js("return getComputedStyle(document.querySelector('.scheme-art .n')).transitionDuration === '0s';")
    print('Eye: each verification reaches the root before a blink; signatures change only while closed')


def main() -> None:
    default_firefox = shutil.which('firefox') or '/Applications/Firefox.app/Contents/MacOS/firefox'
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--base-url', type=local_url, default='http://127.0.0.1:8000')
    parser.add_argument('--firefox', default=default_firefox, help='Firefox executable (PATH or absolute path)')
    parser.add_argument('--output-dir', type=Path, help='Retained screenshot directory (default: a new temporary directory)')
    parser.add_argument('--marionette-port', type=int, default=0, help='Local driver port; 0 selects a free port')
    args = parser.parse_args()
    if not __debug__:
        parser.error('Run without -O: this audit uses assertions.')
    binary = shutil.which(args.firefox)
    if binary is None or not Path(binary).is_file():
        parser.error('Firefox was not found; supply --firefox /path/to/firefox.')
    if not 0 <= args.marionette_port <= 65535:
        parser.error('--marionette-port must be in 0..65535.')
    if args.marionette_port:
        with socket.socket() as probe:
            probe.bind(('127.0.0.1', args.marionette_port))
    output = (args.output_dir or Path(tempfile.mkdtemp(prefix='ots-browser-check-'))).resolve()
    output.mkdir(parents=True, exist_ok=True)
    config = json.loads((ROOT / 'challenges.json').read_text())
    print('Auditing seeded local preview:', args.base_url)
    print('Screenshots:', output)
    with firefox_session(binary, args.marionette_port or free_port()) as browser:
        audit(browser, args.base_url, output, config)
    with firefox_session(binary, args.marionette_port or free_port(), reduced_motion=False) as browser:
        audit_eye_motion(browser, args.base_url)
    print('Browser audit passed. Screenshots:', output)


if __name__ == '__main__':
    main()
