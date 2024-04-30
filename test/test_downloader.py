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
import subprocess
import os.path
import tempfile
import extern
import sys
import json


sys.path = [os.path.join(os.path.dirname(os.path.realpath(__file__)),'..')]+sys.path

from zenodo_backpack import ZenodoBackpackDownloader


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

if __name__ == "__main__":
    # Setup debug logging
    import logging
    # logging.basicConfig(level=logging.DEBUG)
    unittest.main()
