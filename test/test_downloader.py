#!/usr/bin/env python3

#=======================================================================
# Authors: Ben Woodcroft
#
# Unit tests.
#
# Copyright
#
# This is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# Distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.	See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License.
# If not, see <http://www.gnu.org/licenses/>.
#=======================================================================

import unittest
import os.path
import sys
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
import requests

sys.path = [os.path.join(os.path.dirname(os.path.realpath(__file__)),'..')]+sys.path

from zenodo_backpack import ZenodoBackpackDownloader
import zenodo_backpack


class Tests(unittest.TestCase):
    maxDiff = None

    def test_newest_version(self):
        doi = '10.5281/zenodo.5523588'

        record = ZenodoBackpackDownloader()._retrieve_record_ID(doi)
        ret = ZenodoBackpackDownloader()._retrieve_record_metadata(record, None)
        self.assertEqual([
            {
            "id": "82fd2d88-5d4e-48b6-9209-18e3a4518737",
            "key": "S3.metapackage_20211101.smpkg.tar.gz",
            "size": 751003966,
            "checksum": "md5:c460ca3cf49069ebc67dc5d6040f48d5",
            "links": {
                "self": "https://zenodo.org/api/records/5523588/files/S3.metapackage_20211101.smpkg.tar.gz/content"
            }
            }
        ], ret[1])

    def test_non_newest_version(self):
        # doi = '10.5281/zenodo.5739611'
        target_version = '3.2.1'
        newer_recordID = '10982929'

        ret = ZenodoBackpackDownloader()._retrieve_record_metadata(
            newer_recordID, target_version)
        self.assertEqual([
          {
            "id": "f6330110-a232-4f5e-9870-101896ed0067",
            "key": "S3.2.1.GTDB_r214.metapackage_20231006.smpkg.zb.tar.gz",
            "size": 1308380224,
            "checksum": "md5:61595820b5b01bf3eb04c92ff8cad951",
            "links": {
              "self": "https://zenodo.org/api/records/8419620/files/S3.2.1.GTDB_r214.metapackage_20231006.smpkg.zb.tar.gz/content"
            }
          }
        ], ret[1])

    def test_download_and_verify_and_extract(self):
        doi = '10.5281/zenodo.11438051'

        with tempfile.TemporaryDirectory() as tmpdirname:
            # Grab the newest version
            ZenodoBackpackDownloader().download_and_extract(tmpdirname, doi)

    def test_download_and_verify_and_extract_with_version(self):
        doi = '10.5281/zenodo.11438051'

        with tempfile.TemporaryDirectory() as tmpdirname:
            # Grab the newest version
            ZenodoBackpackDownloader().download_and_extract(tmpdirname, doi, version='0.0.1')

    def test_download_and_verify_and_extract_with_bad_version(self):
        doi = '10.5281/zenodo.11438051'

        with self.assertRaises(zenodo_backpack.ZenodoBackpackVersionException):
            with tempfile.TemporaryDirectory() as tmpdirname:
                # Grab the newest version
                ZenodoBackpackDownloader().download_and_extract(tmpdirname, doi, version='0.0.0.2')

    def test_resume_download(self):
        content = b"0123456789" * 1024

        class RangeRequestHandler(BaseHTTPRequestHandler):
            def do_GET(self):
                if self.path != '/file':
                    self.send_response(404)
                    self.end_headers()
                    return
                start = 0
                range_header = self.headers.get('Range')
                if range_header:
                    start = int(range_header.split('=')[1].split('-')[0])
                    self.send_response(206)
                    self.send_header('Content-Range', f'bytes {start}-{len(content) - 1}/{len(content)}')
                    self.send_header('Content-Length', str(len(content) - start))
                else:
                    self.send_response(200)
                    self.send_header('Content-Length', str(len(content)))
                self.end_headers()
                self.wfile.write(content[start:])

        server = HTTPServer(('localhost', 0), RangeRequestHandler)
        thread = threading.Thread(target=server.serve_forever)
        thread.daemon = True
        thread.start()

        try:
            url = f'http://localhost:{server.server_port}/file'
            with tempfile.TemporaryDirectory() as tmpdirname:
                partial_path = os.path.join(tmpdirname, 'download.bin')
                r = requests.get(url, headers={'Range': 'bytes=0-999'})
                with open(partial_path, 'wb') as f:
                    f.write(r.content)
                ZenodoBackpackDownloader()._download_file(url, partial_path)
                with open(partial_path, 'rb') as f:
                    self.assertEqual(f.read(), content)
        finally:
            server.shutdown()
            thread.join()

if __name__ == "__main__":
    # Setup debug logging
    # import logging
    # logging.basicConfig(level=logging.DEBUG)
    unittest.main()
