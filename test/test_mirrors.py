#!/usr/bin/env python3

# Offline tests for downloading via mirrors listed in the Zenodo record as
# related identifiers ("Is identical to"). Zenodo itself is faked with a local
# HTTP server and monkeypatched metadata retrieval.

import hashlib
import os.path
import shutil
import sys
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer

sys.path = [os.path.join(os.path.dirname(os.path.realpath(__file__)), '..')] + sys.path

import zenodo_backpack
from zenodo_backpack import ZenodoBackpackCreator, ZenodoBackpackDownloader, mirror_urls_from_metadata

DATA = os.path.join(os.path.dirname(os.path.realpath(__file__)), 'data', 'test_folder1')
ARCHIVE_NAME = 'test_folder1.zb.tar.gz'
DATA_VERSION = '0.1'


class Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp()
        archive = os.path.join(cls.tmp, ARCHIVE_NAME)
        ZenodoBackpackCreator().create(DATA, archive, DATA_VERSION)
        with open(archive, 'rb') as f:
            cls.content = f.read()
        cls.md5 = hashlib.md5(cls.content).hexdigest()
        content = cls.content
        # Same size as the real archive but different bytes
        corrupt = bytes(b ^ 0xff for b in content[:100]) + content[100:]
        cls.requests_log = requests_log = []

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def _body(self):
                path = self.path.split('?')[0]
                if path in ('/zenodo/' + ARCHIVE_NAME, '/good/' + ARCHIVE_NAME):
                    return content
                if path == '/corrupt/' + ARCHIVE_NAME:
                    return corrupt
                if path == '/short/' + ARCHIVE_NAME:
                    return content[:-10]
                if path == '/html':
                    return b'<html>a landing page</html>'
                return None

            def _respond(self, send_body):
                requests_log.append((self.command, self.path))
                body = self._body()
                if body is None:
                    self.send_response(404)
                    self.send_header('Content-Length', '0')
                    self.end_headers()
                    return
                start = 0
                range_header = self.headers.get('Range')
                if range_header:
                    start = int(range_header.split('=')[1].split('-')[0])
                    self.send_response(206)
                    self.send_header('Content-Range', 'bytes {}-{}/{}'.format(start, len(body) - 1, len(body)))
                else:
                    self.send_response(200)
                self.send_header('Content-Length', str(len(body) - start))
                self.end_headers()
                if send_body:
                    self.wfile.write(body[start:])

            def do_GET(self):
                self._respond(True)

            def do_HEAD(self):
                self._respond(False)

        cls.server = HTTPServer(('localhost', 0), Handler)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.base = 'http://localhost:{}'.format(cls.server.server_port)

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.thread.join()
        shutil.rmtree(cls.tmp)

    def setUp(self):
        del self.requests_log[:]

    def url(self, kind):
        return '{}/{}/{}'.format(self.base, kind, ARCHIVE_NAME)

    def zenodo_url(self):
        return self.url('zenodo')

    def metadata(self, related_identifiers=None, files=None):
        if files is None:
            files = [{
                'key': ARCHIVE_NAME,
                'size': len(self.content),
                'checksum': 'md5:' + self.md5,
                'links': {'self': self.zenodo_url()},
            }]
        md = {'version': DATA_VERSION}
        if related_identifiers is not None:
            md['related_identifiers'] = related_identifiers
        return {'metadata': md, 'files': files}

    def mirrors_rel(self, *urls):
        return [{'identifier': u, 'relation': 'isIdenticalTo', 'scheme': 'url'} for u in urls]

    def downloader(self, metadata):
        d = ZenodoBackpackDownloader()
        d._retrieve_record_ID = lambda doi: '12345'
        d._retrieve_record_metadata = lambda record_id, version: (metadata, metadata['files'])
        return d

    def download(self, metadata, **kwargs):
        d = self.downloader(metadata)
        with tempfile.TemporaryDirectory() as out:
            zb = d.download_and_extract(out, '10.5281/zenodo.12345', **kwargs)
            self.assertEqual(zb.data_version_string(), DATA_VERSION)
            self.assertFalse(os.path.exists(os.path.join(out, ARCHIVE_NAME)))

    def gets(self):
        return [p for (c, p) in self.requests_log if c == 'GET']

    # --- parsing related identifiers

    def test_mirror_urls_from_metadata(self):
        md = {'metadata': {'related_identifiers': [
            {'identifier': 'https://a.example/x.tar.gz', 'relation': 'isIdenticalTo', 'scheme': 'url'},
            {'identifier': 'https://github.com/x/y', 'relation': 'isSupplementTo', 'scheme': 'url'},
            {'identifier': '10.1093/foo', 'relation': 'isIdenticalTo', 'scheme': 'doi'},
            {'identifier': 'https://b.example/x.tar.gz', 'relation_type': {'id': 'isidenticalto'}, 'scheme': 'url'},
            {'identifier': 'https://a.example/x.tar.gz', 'relation': 'isidenticalto', 'scheme': 'URL'},
        ]}}
        self.assertEqual(['https://a.example/x.tar.gz', 'https://b.example/x.tar.gz'],
                         mirror_urls_from_metadata(md))
        self.assertEqual([], mirror_urls_from_metadata({'metadata': {}}))

    # --- download_and_extract

    def test_no_mirrors_uses_zenodo(self):
        self.download(self.metadata())
        self.assertEqual(['/zenodo/' + ARCHIVE_NAME], self.gets())

    def test_good_mirror_used_in_preference(self):
        self.download(self.metadata(self.mirrors_rel(self.url('good'))))
        self.assertEqual(['/good/' + ARCHIVE_NAME], self.gets())

    def test_use_mirrors_false(self):
        self.download(self.metadata(self.mirrors_rel(self.url('good'))), use_mirrors=False)
        self.assertEqual(['/zenodo/' + ARCHIVE_NAME], self.gets())

    def test_404_mirror_falls_back(self):
        self.download(self.metadata(self.mirrors_rel(self.url('missing'))))
        # 404 is not retried
        self.assertEqual(['/missing/' + ARCHIVE_NAME, '/zenodo/' + ARCHIVE_NAME], self.gets())

    def test_corrupt_mirror_falls_back(self):
        self.download(self.metadata(self.mirrors_rel(self.url('corrupt'))))
        self.assertEqual(['/corrupt/' + ARCHIVE_NAME, '/zenodo/' + ARCHIVE_NAME], self.gets())

    def test_wrong_size_mirror_falls_back(self):
        self.download(self.metadata(self.mirrors_rel(self.base + '/html', self.url('short'))))
        self.assertEqual(['/html', '/short/' + ARCHIVE_NAME, '/zenodo/' + ARCHIVE_NAME], self.gets())

    def test_dead_mirror_falls_back(self):
        self.download(self.metadata(self.mirrors_rel('http://localhost:1/' + ARCHIVE_NAME)),
                      download_retries=1)
        self.assertEqual(['/zenodo/' + ARCHIVE_NAME], self.gets())

    def test_mirrors_tried_in_record_order(self):
        self.download(self.metadata(self.mirrors_rel(self.url('missing'), self.url('good'))))
        self.assertEqual(['/missing/' + ARCHIVE_NAME, '/good/' + ARCHIVE_NAME], self.gets())

    def test_all_sources_bad_raises(self):
        md = self.metadata(self.mirrors_rel(self.url('corrupt')))
        md['files'][0]['links']['self'] = self.url('missing')
        with self.assertRaises(zenodo_backpack.ZenodoConnectionException):
            self.download(md)

    def test_multiple_files_raises(self):
        f = self.metadata()['files'][0]
        with self.assertRaises(zenodo_backpack.ZenodoBackpackMalformedException):
            self.download(self.metadata(files=[f, dict(f, key='other.tar.gz')]))

    def test_partial_download_resumed_from_mirror(self):
        d = self.downloader(self.metadata(self.mirrors_rel(self.url('good'))))
        with tempfile.TemporaryDirectory() as out:
            with open(os.path.join(out, ARCHIVE_NAME), 'wb') as f:
                f.write(self.content[:50])
            d.download_and_extract(out, '10.5281/zenodo.12345')
        self.assertEqual(['/good/' + ARCHIVE_NAME], self.gets())

    # --- check_mirrors

    def test_check_mirrors_from_record(self):
        d = self.downloader(self.metadata(self.mirrors_rel(self.url('good'), self.url('corrupt'))))
        results = d.check_mirrors('10.5281/zenodo.12345')
        self.assertEqual([(self.url('good'), zenodo_backpack.MIRROR_OK),
                          (self.url('corrupt'), zenodo_backpack.MIRROR_MD5_MISMATCH)],
                         [(r.url, r.status) for r in results])

    def test_check_candidate_mirrors(self):
        # Candidate mirrors need not be in the record
        d = self.downloader(self.metadata())
        results = d.check_mirrors('10.5281/zenodo.12345', mirrors=[
            self.url('good'), self.url('short'), self.url('missing'), 'http://localhost:1/x'])
        self.assertEqual([zenodo_backpack.MIRROR_OK, zenodo_backpack.MIRROR_SIZE_MISMATCH,
                          zenodo_backpack.MIRROR_UNREACHABLE, zenodo_backpack.MIRROR_UNREACHABLE],
                         [r.status for r in results])

    def test_check_mirrors_size_only(self):
        d = self.downloader(self.metadata())
        results = d.check_mirrors('10.5281/zenodo.12345', size_only=True, mirrors=[
            self.url('good'), self.url('corrupt'), self.url('short')])
        # corrupt has the right size, so passes a size-only check
        self.assertEqual([zenodo_backpack.MIRROR_OK, zenodo_backpack.MIRROR_OK,
                          zenodo_backpack.MIRROR_SIZE_MISMATCH],
                         [r.status for r in results])
        self.assertEqual([], self.gets())

    def test_check_mirrors_none_listed(self):
        d = self.downloader(self.metadata())
        self.assertEqual([], d.check_mirrors('10.5281/zenodo.12345'))


if __name__ == '__main__':
    unittest.main()
