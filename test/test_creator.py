#!/usr/bin/env python3

import unittest
import os.path
import sys
import tempfile

sys.path = [os.path.join(os.path.dirname(os.path.realpath(__file__)),'..')]+sys.path

import zenodo_backpack
from zenodo_backpack import ZenodoBackpackCreator, ZenodoBackpackDownloader

DATA = os.path.join(os.path.dirname(os.path.realpath(__file__)), 'data', 'test_folder1')


class Tests(unittest.TestCase):
    def _round_trip(self, output_name, expected_name, expected_magic, **kwargs):
        with tempfile.TemporaryDirectory() as tmp:
            out = os.path.join(tmp, output_name)
            ZenodoBackpackCreator().create(DATA, out, '0.1', **kwargs)
            archive = os.path.join(tmp, expected_name)
            self.assertTrue(os.path.isfile(archive))
            with open(archive, 'rb') as f:
                self.assertEqual(f.read(4)[:len(expected_magic)], expected_magic)

            extract_dir = os.path.join(tmp, 'extracted')
            os.mkdir(extract_dir)
            folder = ZenodoBackpackDownloader()._extract_archive(archive, extract_dir)
            self.assertEqual(folder.rstrip('/'), 'test_folder1.zb')
            zb = zenodo_backpack.acquire(path=os.path.join(extract_dir, folder), md5sum=True, version='0.1')
            self.assertEqual(zb.data_version_string(), '0.1')
            return os.path.getsize(archive)

    def test_gzip_default(self):
        self._round_trip('out', 'out.zb.tar.gz', b'\x1f\x8b')

    def test_gzip_explicit_extension(self):
        self._round_trip('out.tar.gz', 'out.tar.gz', b'\x1f\x8b')

    def test_gzip_level(self):
        self._round_trip('out.tar.gz', 'out.tar.gz', b'\x1f\x8b', compression_level=1)

    def test_zstd_inferred_from_extension(self):
        self._round_trip('out.tar.zst', 'out.tar.zst', b'\x28\xb5\x2f\xfd')

    def test_zstd_explicit(self):
        self._round_trip('out', 'out.zb.tar.zst', b'\x28\xb5\x2f\xfd', compression='zstd')

    def test_zstd_level(self):
        self._round_trip('out.tar.zst', 'out.tar.zst', b'\x28\xb5\x2f\xfd', compression='zstd', compression_level=19)

    def test_bad_level(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(ValueError):
                ZenodoBackpackCreator().create(DATA, os.path.join(tmp, 'out.tar.gz'), '0.1', compression_level=10)
            with self.assertRaises(ValueError):
                ZenodoBackpackCreator().create(DATA, os.path.join(tmp, 'out.tar.zst'), '0.1', compression_level=23)

    def test_mismatched_extension(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(ValueError):
                ZenodoBackpackCreator().create(DATA, os.path.join(tmp, 'out.tar.gz'), '0.1', compression='zstd')
            with self.assertRaises(ValueError):
                ZenodoBackpackCreator().create(DATA, os.path.join(tmp, 'out.tar.zst'), '0.1', compression='gzip')

    def test_bad_compression(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(ValueError):
                ZenodoBackpackCreator().create(DATA, os.path.join(tmp, 'out'), '0.1', compression='bzip2')


if __name__ == "__main__":
    unittest.main()
