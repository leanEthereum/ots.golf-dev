"""Owner drawings cannot escape their source identity, revision or image context."""
import json
import unittest
from types import SimpleNamespace
from unittest.mock import patch

import httpx
from sqlalchemy import select

from app import signature_diagram as diagrams
from app.config import settings
from app.db import Submission
from app.signature_diagram_format import (MAX_IMAGE_BYTES, MAX_TOTAL_BYTES, parse_registry, validate_svg)
import seed_demo
import test_riscv_track

SID, REPO = '1' * 32, 'owner/submissions'
SVG = b'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 760 640"><path d="M0 0L10 10"/></svg>'
ENTRY = {'commit': 'c' * 40, 'contract': 'd' * 64,
         'image': 'signature-diagrams/test.svg', 'alt': 'A hand-drawn scheme.'}


def registry(entries=None):
    return json.dumps({'version': 1, 'diagrams': entries if entries is not None else {SID: ENTRY}}).encode()


class DiagramFormatTests(unittest.TestCase):
    def test_registry_paths_pins_and_bad_entry_isolation(self):
        for changes in [{'image': '../escape.svg'}, {'image': 'https://example.com/a.svg'},
                        {'image': 'signature-diagrams/a/b.svg'}, {'image': 'signature-diagrams/%61.svg'},
                        {'commit': 'main'}, {'contract': None}, {'alt': ''}, {'alt': '<' * 4097}]:
            valid, errors = parse_registry(registry({SID: ENTRY, '2' * 32: {**ENTRY, **changes}}))
            self.assertEqual(list(valid), [SID])
            self.assertEqual(list(errors), ['2' * 32])
        for raw in [b'{"version":1,"version":1,"diagrams":{}}',
                    b'{"version":true,"diagrams":{}}', b'{"version":1,"diagrams":[]}']:
            with self.assertRaises(ValueError):
                parse_registry(raw)

    def test_static_svg_and_approved_drawings(self):
        self.assertEqual(validate_svg(SVG), (760, 640))
        for file in diagrams.FIXTURES.glob('*.svg'):
            self.assertEqual(validate_svg(file.read_bytes()), (760, 640))
        gradient = SVG.replace(b'<path', b'<defs><linearGradient id="g"><stop offset="0"/></linearGradient></defs><path fill="url(#g)"')
        validate_svg(gradient)

    def test_rejects_active_external_and_unbounded_svg(self):
        for payload in [b'<script>alert(1)</script>', b'<foreignObject/>', b'<image href="https://example.com/a"/>',
                        b'<g onclick="alert(1)"/>', b'<use href="https://example.com/a.svg#x"/>',
                        b'<style>@import "https://example.com/a.css";</style>',
                        b'<style>g{fill:url(https://example.com/a)}</style>',
                        b'<g style="fill:u\\72l(https://example.com/a)"/>', b'<animate/>']:
            with self.subTest(payload=payload), self.assertRaises(ValueError):
                validate_svg(SVG.replace(b'</svg>', payload + b'</svg>'))
        for raw in [b'<!DOCTYPE svg [<!ENTITY x "y">]>' + SVG, SVG.decode().encode('utf-16'),
                    SVG.replace(b'760 640', b'NaN 640'), SVG.replace(b'760 640', b'0 640'),
                    SVG + b' ' * MAX_IMAGE_BYTES]:
            with self.assertRaises(ValueError):
                validate_svg(raw)


class DiagramCacheTests(unittest.TestCase):
    def setUp(self):
        self.cache = diagrams.DiagramCache()
        self.responses, self.requests = [], []
        client = httpx.Client
        for change in [patch.object(settings, 'submissions_repo', REPO),
                       patch.object(diagrams.httpx, 'Client', side_effect=lambda **kw:
                                    client(transport=httpx.MockTransport(self.handle), **kw))]:
            change.start()
            self.addCleanup(change.stop)

    def handle(self, request):
        self.requests.append(request)
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response

    def ref(self, revision):
        self.responses.append(httpx.Response(200, json={'object': {'sha': revision * 40}}))

    def load(self, revision='a', raw=SVG):
        self.ref(revision)
        self.responses.extend([httpx.Response(200, content=registry()), httpx.Response(200, content=raw)])
        self.cache.refresh()

    def test_cold_start_same_revision_and_image_only_edits(self):
        self.load()
        self.assertEqual(self.cache.snapshot[1][SID]['data'], SVG)
        self.assertEqual([r.url.params.get('ref') for r in self.requests[1:]], ['a' * 40] * 2)
        snapshot = self.cache.snapshot
        self.ref('a')
        self.cache.refresh()
        self.assertIs(self.cache.snapshot, snapshot)
        changed = SVG.replace(b'L10 10', b'L20 20')
        self.load('b', changed)
        self.assertEqual(self.cache.snapshot[1][SID]['data'], changed)
        self.assertTrue(all(r.url.params['ref'] == 'b' * 40 for r in self.requests[-2:]))

    def test_deletion_missing_registry_and_malformed_registry_clear(self):
        for response in [httpx.Response(200, content=registry({})), httpx.Response(404),
                         httpx.Response(200, content=b'{bad')]:
            self.cache.revision = None
            self.load()
            self.ref('b')
            self.responses.append(response)
            self.cache.refresh()
            self.assertEqual(self.cache.snapshot, (REPO, {}))

    def test_image_failure_retries_same_revision_without_partial_publication(self):
        self.load()
        snapshot = self.cache.snapshot
        self.ref('b')
        self.responses.extend([httpx.Response(200, content=registry()), httpx.Response(503)])
        self.cache.refresh()
        self.assertIs(self.cache.snapshot, snapshot)
        self.assertEqual(self.cache.revision, 'a' * 40)
        self.load('b')
        self.assertEqual(self.cache.revision, 'b' * 40)

    def test_invalid_or_missing_image_does_not_hide_valid_sibling(self):
        for bad in [httpx.Response(404), httpx.Response(200, content=b'not svg')]:
            self.cache.revision = None
            self.ref('a')
            self.responses.extend([httpx.Response(200, content=registry({
                SID: ENTRY, '2' * 32: {**ENTRY, 'image': 'signature-diagrams/missing.svg'}})),
                httpx.Response(200, content=SVG), bad])
            self.cache.refresh()
            self.assertEqual(list(self.cache.snapshot[1]), [SID])

    def test_switching_repository_does_not_keep_old_drawings(self):
        self.load()
        with patch.object(settings, 'submissions_repo', 'another/repository'):
            self.responses.append(httpx.Response(503))
            self.cache.refresh()
        self.assertEqual(self.cache.snapshot, ('another/repository', {}))

    def test_snapshot_size_bound(self):
        self.ref('a')
        self.responses.extend([httpx.Response(200, content=registry()), httpx.Response(200, content=SVG)])
        with patch.object(diagrams, 'MAX_TOTAL_BYTES', len(SVG) - 1):
            self.cache.refresh()
        self.assertEqual(self.cache.snapshot, (REPO, {}))


class DiagramPageTests(unittest.TestCase):
    setUp = test_riscv_track.RiscvTrackTests.setUp
    tearDown = test_riscv_track.RiscvTrackTests.tearDown

    def real(self):
        seed_demo.refresh(self.session)
        sub = next(s for s in self.session.scalars(select(Submission)) if s.track == 'upper-riscv')
        sub.id, sub.commit = SID, ENTRY['commit']
        sub.pr_number, sub.pr_url = 5, f'https://github.com/{REPO}/pull/5'
        sub.detail = json.dumps({'contract': ENTRY['contract']})
        sub.status = 'verified'
        self.session.commit()
        return sub

    def test_real_drawing_pins_all_identity_and_both_upper_tracks(self):
        sub = self.real()
        with patch.object(settings, 'submissions_repo', REPO), \
             patch.object(diagrams.cache, 'snapshot', (REPO, {SID: diagrams._image(ENTRY, SVG)})):
            for track in ['upper-riscv', 'upper-compressions']:
                sub.track = track
                self.assertIsNotNone(diagrams.for_submission(sub))
            for field, value in [('track', 'lower-generality-1'), ('commit', 'f' * 40),
                                 ('status', 'failed'), ('id', '2' * 32),
                                 ('detail', json.dumps({'contract': 'f' * 64})),
                                 ('pr_url', 'https://github.com/fork/repo/pull/5')]:
                old = getattr(sub, field)
                setattr(sub, field, value)
                self.assertIsNone(diagrams.for_submission(sub), field)
                setattr(sub, field, old)

    def test_render_is_network_free_image_context_and_deletion_returns_404(self):
        sub = self.real()
        with patch.object(settings, 'submissions_repo', REPO), \
             patch.object(diagrams.cache, 'snapshot', (REPO, {SID: diagrams._image(ENTRY, SVG)})), \
             patch.object(diagrams.httpx, 'Client', side_effect=AssertionError('page fetched GitHub')):
            page = self.client.get(f'/submissions/{SID}')
            self.assertIn('Signature scheme', page.text)
            self.assertIn(f'src="/submissions/{SID}/signature-diagram.svg"', page.text)
            self.assertNotIn(SVG.decode(), page.text)
            image = self.client.get(f'/submissions/{SID}/signature-diagram.svg')
            self.assertEqual(image.content, SVG)
            self.assertEqual(image.headers['Content-Security-Policy'],
                             "default-src 'none'; style-src 'unsafe-inline'; sandbox")
            self.assertEqual(image.headers['X-Content-Type-Options'], 'nosniff')
            self.assertEqual(self.client.get(f'/submissions/{SID}/signature-diagram.svg',
                             headers={'If-None-Match': image.headers['ETag']}).status_code, 304)
        with patch.object(diagrams.cache, 'snapshot', (REPO, {})):
            self.assertNotIn('Signature scheme', self.client.get(f'/submissions/{SID}').text)
            self.assertEqual(self.client.get(f'/submissions/{SID}/signature-diagram.svg').status_code, 404)

    def test_local_preview_never_falls_back_in_production(self):
        path = '/diagram-previews/440fbe4103a5cfff1f213e25ac09bfd9'
        with patch.object(settings, 'environment', 'production'):
            self.assertEqual(self.client.get(path).status_code, 404)
            self.assertEqual(self.client.get(path + '/image.svg').status_code, 404)
            fake = SimpleNamespace(track='upper-riscv', detail_dict={
                'demo': True, 'fixture_id': 'upper-riscv-satoshi-nakamoto-2'})
            self.assertIsNone(diagrams.for_submission(fake))
