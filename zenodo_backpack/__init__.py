import hashlib
import requests
import shutil
import os
import logging
import json
from tqdm import tqdm
import tarfile
import tempfile
import sys
import gzip

from .version import __version__

class ZenodoBackpackMalformedException(Exception):
    pass  # No implementation needed


class ZenodoBackpackVersionException(Exception):
    pass


class ZenodoConnectionException(Exception):
    pass

class BrokenSymlinkException(Exception):
    pass

class DownloadSizeMismatchException(Exception):
    pass

CURRENT_ZENODO_BACKPACK_VERSION = 1

# Mirrors are listed in the Zenodo record as related identifiers with this
# relation (DataCite "IsIdenticalTo") and the URL scheme.
MIRROR_RELATION = 'isidenticalto'
MIRROR_SCHEME = 'url'

# (connect, read) timeouts for downloads, in seconds
DOWNLOAD_TIMEOUT = (15., 120.)

MIRROR_OK = 'OK'
MIRROR_SIZE_MISMATCH = 'SIZE_MISMATCH'
MIRROR_MD5_MISMATCH = 'MD5_MISMATCH'
MIRROR_UNREACHABLE = 'UNREACHABLE'

PAYLOAD_DIRECTORY_KEY = 'payload_directory'
PAYLOAD_DIRECTORY = 'payload_directory'
DATA_VERSION = 'data_version'
ZB_VERSION = 'zenodo_backpack_version'

GZIP = 'gzip'
ZSTD = 'zstd'
COMPRESSION_TYPES = (GZIP, ZSTD)
COMPRESSION_EXTENSIONS = {GZIP: '.tar.gz', ZSTD: '.tar.zst'}
DEFAULT_COMPRESSION_LEVELS = {GZIP: 9, ZSTD: 3}
COMPRESSION_LEVEL_RANGES = {GZIP: (0, 9), ZSTD: (1, 22)}
ARCHIVE_SUFFIXES = ('.tar.gz', '.tar.zst', '.tar.zstd')

_GZIP_MAGIC = b'\x1f\x8b'
_ZSTD_MAGIC = b'\x28\xb5\x2f\xfd'


def mirror_urls_from_metadata(metadata):
    '''Return the mirror URLs listed in a Zenodo record's metadata, in order.

    A mirror is a related identifier with relation "Is identical to" and
    scheme "url". Both the legacy Zenodo API form ({"relation": "isIdenticalTo"})
    and the InvenioRDM form ({"relation_type": {"id": "isidenticalto"}}) are
    understood.'''
    related = (metadata.get('metadata') or {}).get('related_identifiers') or []
    urls = []
    for r in related:
        relation = r.get('relation')
        if relation is None:
            relation = (r.get('relation_type') or {}).get('id', '')
        scheme = r.get('scheme') or ''
        identifier = r.get('identifier') or ''
        if str(relation).lower() == MIRROR_RELATION and str(scheme).lower() == MIRROR_SCHEME \
                and identifier.startswith(('http://', 'https://')):
            if identifier not in urls:
                urls.append(identifier)
    return urls


class MirrorCheckResult:
    '''Result of checking one mirror URL against a Zenodo record.'''
    def __init__(self, url, status, detail=''):
        self.url = url
        self.status = status
        self.detail = detail

    @property
    def ok(self):
        return self.status == MIRROR_OK

    def __repr__(self):
        return 'MirrorCheckResult({!r}, {!r}, {!r})'.format(self.url, self.status, self.detail)


def _zstd_open(path, mode, level=None):
    '''Open a zstd-compressed file for binary reading ('rb') or writing
    ('wb'). Uses the standard library's compression.zstd module (Python
    3.14+) when available, otherwise the zstandard package.'''
    try:
        from compression import zstd
    except ImportError:
        zstd = None
    if zstd is not None:
        if mode == 'wb':
            return zstd.open(path, mode, level=level)
        return zstd.open(path, mode)

    try:
        import zstandard
    except ImportError:
        raise ImportError(
            'zstd support requires Python 3.14+ or the "zstandard" package '
            '(e.g. pip install zstandard)')
    if mode == 'wb':
        kwargs = {} if level is None else {'level': level}
        return zstandard.ZstdCompressor(**kwargs).stream_writer(
            open(path, 'wb'), closefd=True)
    return zstandard.ZstdDecompressor().stream_reader(
        open(path, 'rb'), read_across_frames=True, closefd=True)


def _detect_compression(path):
    '''Return GZIP or ZSTD based on the file's magic bytes, or None.'''
    with open(path, 'rb') as f:
        magic = f.read(4)
    if magic.startswith(_GZIP_MAGIC):
        return GZIP
    if magic.startswith(_ZSTD_MAGIC):
        return ZSTD
    return None

class ZenodoBackpack:
    def __init__(self, base_directory):
        self.base_directory = base_directory

        try:
            with open(os.path.join(self.base_directory, 'CONTENTS.json')) as jsonfile:
                self.contents = json.load(jsonfile)
        except:
            raise ZenodoBackpackMalformedException('Failed to load CONTENTS.json')
        #self.zenodo_backpack_version = self.contents[ZB_VERSION]
        #self.data_version = self.contents[DATA_VERSION]

    def payload_directory_string(self, enter_single_payload_directory=False):
        '''Returns the payload directory string.

        Parameters
        ----------
        enter_single_payload_directory: bool
            If True, the payload directory contains a single directory. Return
            that directory instead of the payload directory itself.
        '''
        payload_dir = os.path.join(self.base_directory, self.contents[PAYLOAD_DIRECTORY_KEY])
        if enter_single_payload_directory:
            files = os.listdir(payload_dir)
            if len(files) != 1:
                raise ZenodoBackpackMalformedException(
                    'Payload directory contains more than one file, but enter_single_payload_directory was set to True.')
            payload_dir = os.path.join(payload_dir, files[0])
            if not os.path.isdir(payload_dir):
                raise ZenodoBackpackMalformedException(
                    'Payload directory contains a file, not a directory, but enter_single_payload_directory was set to True.')
            return payload_dir
        else:
            return payload_dir

    def data_version_string(self):
        return self.contents[DATA_VERSION]

    def zenodo_backpack_version_string(self):
        return self.contents[ZB_VERSION]


def acquire(path=None, env_var_name=None, md5sum=False, version=None):
    ''' Look for folder corresponding to a path or environmental variable and
    return it.

    Parameters
    ----------
    path: str
        Path to the backpack. Cannot be used with env_var_name.
    env_var_name: str
        Name of an environment variable that contains a path to a backpack
    md5sum: bool
        If True, use the contents.json file to verify files.
    version: str
        Excpected version of the backpack. If not provided, the version in the CONTENTS.json file is checked.
    
    Raises
    ------
    ZenodoBackpackMalformedException: 
        If the environment variable does not point to a valid ZenodoBackpack
        i.e. a directory with a CONTENTS.json in it.
    ZenodoBackpackVersionException:
        If not expected Backpack version
    '''

    if path:
        logging_description = "Path {}".format(path)
        basefolder = path

    elif env_var_name:
        logging_description = f"Environment variable {env_var_name}"
        if env_var_name not in os.environ:
            raise ZenodoBackpackMalformedException(f'Environment variable {env_var_name} was undefined, when it should define the path to the ZenodoBackpack data.')
        else:
            basefolder = os.environ[env_var_name]
    else:
        raise ZenodoBackpackMalformedException()

    if os.path.isdir(basefolder):
        if 'CONTENTS.json' in os.listdir(basefolder):
            logging.info('Retrieval successful. Location of backpack is: {}'.format(basefolder))

            zb = ZenodoBackpack(basefolder)

            if version:
                if version != zb.data_version_string():
                    raise ZenodoBackpackMalformedException(
                f'Version in CONTENTS.json: {zb.data_version_string()} does not match version provided: {version}')
            if md5sum:
                ZenodoBackpackDownloader().verify(zb, passed_version=version)
            return zb

        else:
            raise ZenodoBackpackMalformedException(f"{logging_description} does not contain a CONTENTS.json file, so is not a valid ZenodoBackpack")
    else:
        raise ZenodoBackpackMalformedException(f"{logging_description} is not a directory so cannot hold a ZenodoBackpack")


class ZenodoBackpackDownloader:

    def download_and_extract(self, directory, doi, check_version=True, progress_bar=False, download_retries=3, version=None,
                             use_mirrors=True):
        """Actually do the download, to a given path. Also extract the archive,
        and then call verify on it.

        The Zenodo record is always the authority for the file name, size,
        md5sum and version. If the record lists mirrors (related identifiers
        with relation "Is identical to" and a URL), they are tried first, in
        the order listed, falling back to Zenodo itself. A file from any source
        is only accepted if its md5sum matches the Zenodo record.

        Parameters
        ----------
        directory: str
            Where to download to
        doi: str
            DOI of the Zenodo series
        progress_bar: bool
            If True, display graphical progress bar while downloading from Zenodo
        check_version: bool
            If True, check Zenodo metadata verifies
        download_retries: int
            Number of download attempts per source
        version: None or str
            If None, return the newest version. If specified, target that specific version.
        use_mirrors: bool
            If True (the default), try mirrors listed in the Zenodo record
            before Zenodo itself. If False, only download from Zenodo.

        Returns a ZenodoBackpack object containing the downloaded files
        """
        if doi is None:
            raise ZenodoConnectionException('Record could not get accessed.')
        self._make_sure_path_exists(directory)

        # get record via DOI, then read in json metadata from records_url
        record_id = self._retrieve_record_ID(doi)
        metadata, files = self._retrieve_record_metadata(record_id, version)
        zenodo_file = self._single_file(files)

        filename = zenodo_file['key'].split('/')[-1]
        if not filename.endswith(ARCHIVE_SUFFIXES):
            raise ZenodoBackpackMalformedException(
                "File '{}' in Zenodo record is not a zenodo_backpack archive (expected one of {})".format(
                    filename, ', '.join(ARCHIVE_SUFFIXES)))
        archive_path = os.path.join(directory, filename)

        sources = []
        if use_mirrors:
            mirrors = mirror_urls_from_metadata(metadata)
            if mirrors:
                logging.info('Zenodo record lists {} mirror(s)'.format(len(mirrors)))
            sources.extend(mirrors)
        zenodo_link = zenodo_file['links']['self']
        if zenodo_link not in sources:
            sources.append(zenodo_link)

        self._download_from_sources(
            sources, archive_path, zenodo_file['checksum'], expected_size=zenodo_file.get('size'),
            progress_bar=progress_bar, download_retries=download_retries)

        logging.info('Extracting files from archive...')
        zb_folder = self._extract_archive(archive_path, directory)
        os.remove(archive_path)

        zb_folder = os.path.abspath(os.path.join(directory, zb_folder))
        zb = ZenodoBackpack(zb_folder)

        if not check_version:
            self.verify(zb)
        else:
            self.verify(zb, metadata=metadata)

        return zb

    def check_mirrors(self, doi, version=None, mirrors=None, size_only=False, progress_bar=False, working_directory=None):
        """Check that mirror URLs serve exactly the file in a Zenodo record.

        Parameters
        ----------
        doi: str
            DOI of the Zenodo series
        version: None or str
            If None, use the newest version. If specified, target that specific version.
        mirrors: None or list of str
            URLs to check. If None, check the mirrors listed in the Zenodo
            record. Use this to check a candidate mirror before adding it to
            the record.
        size_only: bool
            If True, only compare the size reported by the server with the
            Zenodo record (no download). Otherwise download the file and
            compare md5sums.
        progress_bar: bool
            Show a progress bar while downloading.
        working_directory: None or str
            Where to temporarily download files to [default: system temporary directory]

        Returns a list of MirrorCheckResult, one per URL, in order.
        """
        record_id = self._retrieve_record_ID(doi)
        metadata, files = self._retrieve_record_metadata(record_id, version)
        zenodo_file = self._single_file(files)
        expected_size = zenodo_file.get('size')
        checksum = zenodo_file['checksum']
        filename = zenodo_file['key'].split('/')[-1]

        if mirrors is None:
            mirrors = mirror_urls_from_metadata(metadata)
            if not mirrors:
                logging.warning('No mirrors are listed in the Zenodo record. To list one, add a related '
                                'identifier with relation "Is identical to" and the mirror URL.')

        results = []
        for url in mirrors:
            logging.info('Checking mirror {}'.format(url))
            if size_only:
                result = self._check_mirror_size(url, expected_size)
            else:
                with tempfile.TemporaryDirectory(dir=working_directory) as tmp:
                    out = os.path.join(tmp, filename)
                    try:
                        self._download_file(url, out, progress_bar=progress_bar, expected_size=expected_size)
                    except DownloadSizeMismatchException as e:
                        result = MirrorCheckResult(url, MIRROR_SIZE_MISMATCH, str(e))
                    except requests.RequestException as e:
                        result = MirrorCheckResult(url, MIRROR_UNREACHABLE, str(e))
                    else:
                        if self._check_hash(out, checksum):
                            result = MirrorCheckResult(url, MIRROR_OK, 'md5sum matches {}'.format(checksum))
                        else:
                            result = MirrorCheckResult(
                                url, MIRROR_MD5_MISMATCH, 'md5sum does not match {}'.format(checksum))
            if result.ok:
                logging.info('{}: {} ({})'.format(url, result.status, result.detail))
            else:
                logging.warning('{}: {} ({})'.format(url, result.status, result.detail))
            results.append(result)
        return results

    def _check_mirror_size(self, url, expected_size):
        try:
            r = requests.head(url, allow_redirects=True, timeout=DOWNLOAD_TIMEOUT)
            if r.status_code >= 400 or r.headers.get('content-length') is None:
                # Some servers don't support HEAD or omit the length; read the GET headers only.
                r.close()
                r = requests.get(url, stream=True, timeout=DOWNLOAD_TIMEOUT)
                r.close()
            r.raise_for_status()
        except requests.RequestException as e:
            return MirrorCheckResult(url, MIRROR_UNREACHABLE, str(e))
        length = r.headers.get('content-length')
        if length is None:
            return MirrorCheckResult(url, MIRROR_UNREACHABLE, 'Server did not report a Content-Length')
        if expected_size is not None and int(length) != int(expected_size):
            return MirrorCheckResult(
                url, MIRROR_SIZE_MISMATCH, 'size {} does not match Zenodo size {}'.format(length, expected_size))
        return MirrorCheckResult(url, MIRROR_OK, 'size {} matches (md5sum not checked)'.format(length))

    def _single_file(self, files):
        if len(files) != 1:
            raise ZenodoBackpackMalformedException(
                'Expected exactly one file in the Zenodo record, found {}: {}'.format(
                    len(files), ', '.join(str(f.get('key')) for f in files)))
        return files[0]

    def _download_from_sources(self, sources, out_file, checksum, expected_size=None, progress_bar=False,
                               download_retries=3):
        """Download a file from the first source that provides it with the
        correct md5sum. Each source is retried up to download_retries times
        for transient errors. Returns the URL that was used."""
        failures = []
        for i, url in enumerate(sources):
            if i > 0 and os.path.exists(out_file):
                # Never resume a partial download from a different source
                os.remove(out_file)
            error = None
            for attempt in range(download_retries):
                try:
                    self._download_file(url, out_file, progress_bar=progress_bar, expected_size=expected_size)
                except DownloadSizeMismatchException as e:
                    error = e
                    break
                except requests.HTTPError as e:
                    error = e
                    if e.response is not None and e.response.status_code < 500:
                        break  # client errors like 404 won't be fixed by retrying
                    logging.warning('Error downloading from {} (attempt {}/{}): {}'.format(
                        url, attempt + 1, download_retries, e))
                except requests.RequestException as e:
                    error = e
                    logging.warning('Error downloading from {} (attempt {}/{}): {}'.format(
                        url, attempt + 1, download_retries, e))
                else:
                    error = None
                    break

            if error is None:
                if self._check_hash(out_file, checksum):
                    logging.info('Downloaded {} with correct checksum'.format(url))
                    return url
                error = 'md5sum does not match Zenodo record ({})'.format(checksum)
            logging.warning('Could not use {}: {}'.format(url, error))
            failures.append('{}: {}'.format(url, error))
            if os.path.exists(out_file):
                os.remove(out_file)

        raise ZenodoConnectionException(
            'Could not download a file with the correct checksum from any source:\n' + '\n'.join(failures))

    def verify(self, zenodo_backpack, metadata=None, passed_version=None):
        """Verify that a downloaded directory is in working order.

        If metadata downloaded from Zenodo is provided, it will be checked as well.

        Reads <CONTENTS.json> (file) within directory containing md5 sums for files a single extracted
        payload folder with an arbitrary name

        Parameters
        ----------
        directory: str
            Location of downloaded and extracted data
        metadata: json dict
            Downloaded metadata from Zenodo containing version information
        passed_version: str
            Passed specific version to verify

        Returns nothing if verification works, otherwise raises
        ZenodoBackpackMalformedException or ZenodoBackpackVersionException
        """



        # extract identifying keys for version and zenodo_backpack_version
        version = zenodo_backpack.data_version_string()
        zenodo_backpack_version = zenodo_backpack.zenodo_backpack_version_string()
        payload_folder = zenodo_backpack.payload_directory_string()

        if metadata:
            logging.info('Verifying version and checksums...')
            metadata_ver = str(metadata['metadata']['version']).strip()

            if str(version).strip() != metadata_ver:
                raise ZenodoBackpackMalformedException(
                    f'Version in CONTENTS.json: {version} does not match version in Zenodo metadata: {metadata_ver}')

        elif passed_version:
            logging.info('Verifying version and checksums...')
            if str(version).strip() != str(passed_version).strip():
                raise ZenodoBackpackMalformedException(
                    f'Version in CONTENTS.json: {version} does not match version provided: {passed_version}')

        else:
            logging.warning('Not using version verification.')
            logging.info('Verifying checksums...')

        if zenodo_backpack_version != CURRENT_ZENODO_BACKPACK_VERSION:
            raise ZenodoBackpackVersionException('Incorrect ZENODO Backpack version: {} Expected: {}'
                                                 .format(zenodo_backpack_version, CURRENT_ZENODO_BACKPACK_VERSION))

        # The rest of contents should only be files with md5 sums.

        for payload_file in zenodo_backpack.contents['md5sums'].keys():
            filepath = os.path.join(os.path.split(payload_folder)[0], payload_file[1:]) # remove slash to enable os.path.join
            if not self._check_hash(filepath, zenodo_backpack.contents['md5sums'][payload_file], metadata=False):
                raise ZenodoBackpackMalformedException('Extracted file md5 sum does not match that in JSON file.')

        logging.info('Verification success.')

    def _retrieve_record_ID(self, doi):
        """Parses provided DOI retrieve associated Zenodo URL which also contains record ID
        Arguments:
            DOI (str): published DOI associated with file uploaded to Zenodo
            version: If None, return the newest version. If specified, target that specific version.
        Returns:
            recordID (str): last part of Zenodo url associated with DOI
        """

        if not doi.startswith('http'):
            doi = 'https://doi.org/' + doi
        try:
            logging.debug(f"Retrieving URL {doi}")
            r = requests.get(doi, timeout=15.)
        except Exception as e:
            raise ZenodoConnectionException('Connection error: {}'.format(e))
        if not r.ok:
            raise ZenodoConnectionException('DOI could not be resolved. Check your DOI is correct.')

        recordID = r.url.split('/')[-1].strip()
        return recordID

    def _retrieve_record_json(self, recordID):
        """Parses provided recordID to access Zenodo API records and download metadata json
        Arguments:
            recordID (str): Zenodo record number
        Returns:
            json response from Zenodo API
        """
        records_url = 'https://zenodo.org/api/records/'

        try:
            r = requests.get(records_url + recordID, timeout=15.)
            return json.loads(r.text)
        except Exception as e:
            raise ZenodoConnectionException('Error during metadata retrieval: {}'.format(e))

    def _retrieve_versions_record_json(self, recordID, version):
        """Parses provided recordID to access Zenodo API records and download metadata json
        Arguments:
            recordID (str): Zenodo record number
            version: (str): Target that specific version.
        Returns:
            json response from Zenodo API
        """
        records_url = 'https://zenodo.org/api/records/'

        try:
            r = requests.get(records_url + recordID + '/versions', timeout=15.)
        except Exception as e:
            raise ZenodoConnectionException('Error during metadata retrieval: {}'.format(e))

        js = json.loads(r.text)
        versions = js['hits']['hits']
        for v in versions:
            if 'version' not in v['metadata']:
                if 'doi' in v['metadata']:
                    bad_doi = v['metadata']['doi']
                else:
                    bad_doi = '???'
                logging.warning(f'Version not found in Zenodo record {bad_doi}. Is the version specified in the record\'s metadata? The authors can update this. But here, skipping this instance.')
                continue
            if v['metadata']['version'] == version:
                return v
        raise ZenodoBackpackVersionException(f'Version {version} not found in Zenodo record {recordID}')

    def _retrieve_record_metadata(self, recordID, version):
        """Parses provided recordID to access Zenodo API records and download metadata json
        Arguments:
            recordID (str): Zenodo record number
            version: (None or str): If None, return the newest version. If specified, target that specific version.
        Returns:
            js (json object): json metadata file retrieved from Zenodo API.
            js['files'] (list): list of files associated with recordID in question
        """
        if version is None:
            js = self._retrieve_record_json(recordID)
        else:
            js = self._retrieve_versions_record_json(recordID, version)
        return js, js['files']

    def _check_hash(self, filename, checksum, metadata=True):
        """Compares MD5 sum of file to checksum
        Arguments:
            filename (str): Path of file to md5sum
            checkmsum: (str): md5 checksum

            returns True if checksum is correct
        """
        if metadata:
            algorithm, value = checksum.split(':')
        else:
            algorithm = 'md5'
            value = checksum

        if not os.path.exists(filename):
            raise FileNotFoundError(filename)
        h = hashlib.new(algorithm)
        with open(filename, 'rb') as f:
            while True:
                data = f.read(4096)
                if not data:
                    break
                h.update(data)
        digest = h.hexdigest()

        return value == digest

    def _download_file(self, file_url, out_file, progress_bar=False, expected_size=None):
        """Download a file to disk
        Streams a file from URL to disk, resuming a partial download of
        out_file if the server supports Range requests.
        Can optionally use tqdm for a visual download bar
        Arguments:
            file_url (str): URL of file to download
            out_file (str): Target file path
            progress_bar (bool): Display graphical progresss bar
            expected_size (int or None): Expected size of the complete file
                in bytes. If the server reports a different size,
                DownloadSizeMismatchException is raised before downloading.
        Raises requests.RequestException (including requests.HTTPError) on
        connection or HTTP errors.
        """
        existing_size = os.path.getsize(out_file) if os.path.exists(out_file) else 0
        if expected_size is not None:
            expected_size = int(expected_size)
            if existing_size == expected_size:
                logging.debug('{} already has the expected size, not downloading'.format(out_file))
                return
            if existing_size > expected_size:
                os.remove(out_file)
                existing_size = 0

        headers = {}
        if existing_size > 0:
            headers['Range'] = 'bytes={}-'.format(existing_size)

        logging.info('Downloading {} to {}'.format(file_url, out_file))
        with requests.get(file_url, stream=True, headers=headers, timeout=DOWNLOAD_TIMEOUT) as r:
            if r.status_code == 416 and existing_size > 0:
                # Nothing more to fetch; the checksum decides if it is complete.
                return
            r.raise_for_status()

            mode = 'wb'
            if r.status_code == 206 and existing_size > 0:
                content_range = r.headers.get('content-range', '')
                if content_range.startswith('bytes {}-'.format(existing_size)):
                    mode = 'ab'
                else:
                    raise requests.HTTPError(
                        'Unexpected Content-Range "{}" when resuming from byte {}'.format(
                            content_range, existing_size), response=r)
            if mode == 'wb':
                # Server ignored the Range header, start from the beginning
                existing_size = 0

            content_length = r.headers.get('content-length')
            total_size = int(content_length) + existing_size if content_length is not None else None
            if expected_size is not None and total_size is not None and total_size != expected_size:
                raise DownloadSizeMismatchException(
                    'Server reports size {} but Zenodo record size is {}'.format(total_size, expected_size))

            bar = None
            if progress_bar:
                bar = tqdm(total=total_size, unit='iB', unit_scale=True, initial=existing_size)
            try:
                with open(out_file, mode) as f:
                    # decode_content=False keeps the exact bytes served, so
                    # Content-Encoding can never alter the archive.
                    for chunk in r.raw.stream(1024 * 1024, decode_content=False):
                        f.write(chunk)
                        if bar is not None:
                            bar.update(len(chunk))
            finally:
                if bar is not None:
                    bar.close()

    def _extract_archive(self, filepath, directory):
        """Extract a gzip or zstd compressed tar archive into directory.

        Returns the common prefix of the archive's member names (i.e. the
        backpack's root folder name).
        """
        logging.debug('Extracting {}'.format(filepath))
        if _detect_compression(filepath) == ZSTD:
            with _zstd_open(filepath, 'rb') as zf:
                with tarfile.open(fileobj=zf, mode='r|') as tf:
                    tf.extractall(directory)
                    names = tf.getnames()
        else:
            with tarfile.open(filepath) as tf:
                names = tf.getnames()
                tf.extractall(directory)
        return os.path.commonprefix(names)

    def _extract_all(self, archive, extract_path):
        for filename in archive:
            shutil.unpack_archive(filename, extract_path)

    def _make_sure_path_exists(self, path):
        """Create directory if it does not exist."""
        if not path:
            return

        if not os.path.exists(path):
            try:
                os.makedirs(path)
            except Exception as e:
                    logging.error('Specified path does not exist: ' + path + '\n')
                    raise e


class ZenodoBackpackCreator:

    def create(self, input_directory, output_file, data_version, force=False,
               compression=None, compression_level=None):


        """Creates Zenodo backpack

                Parameters:
        ----------
        input_directory: str
            Files to be packaged
        output_file: str
            Archive (.tar.gz or .tar.zst) to be created. Automatically appends
            '.zb.tar.gz' or '.zb.tar.zst' if needed.
        data_version:
            Passes the data version of the file to archive

                NOTE!! Same version must be specified in Zenodo metadata when file is uploaded, else error.
        force: True or False
            If True, overwrite an existing output_file if required. If False,
            don't overwrite.
        compression: None, 'gzip' or 'zstd'
            Compression to use. If None, inferred from the output_file
            extension ('.tar.zst' -> zstd), defaulting to gzip.
        compression_level: None or int
            Compression level. gzip: 0-9 (default 9), zstd: 1-22 (default 3).

        Returns nothing, unless input_directory is not a directory or output_file exists, which raises Exceptions
        """

        output_file = str(output_file)
        if compression is None:
            compression = ZSTD if output_file.endswith(('.tar.zst', '.tar.zstd')) else GZIP
        if compression not in COMPRESSION_TYPES:
            raise ValueError('Unknown compression type {}, must be one of {}'.format(
                compression, ', '.join(COMPRESSION_TYPES)))
        if compression_level is None:
            compression_level = DEFAULT_COMPRESSION_LEVELS[compression]
        min_level, max_level = COMPRESSION_LEVEL_RANGES[compression]
        if not isinstance(compression_level, int) or not min_level <= compression_level <= max_level:
            raise ValueError('Compression level for {} must be an integer between {} and {}, found {}'.format(
                compression, min_level, max_level, compression_level))

        if output_file.endswith(ARCHIVE_SUFFIXES):
            if compression == GZIP and not output_file.endswith('.tar.gz'):
                raise ValueError('Output file {} does not end in .tar.gz but gzip compression was requested'.format(output_file))
            if compression == ZSTD and output_file.endswith('.tar.gz'):
                raise ValueError('Output file {} ends in .tar.gz but zstd compression was requested'.format(output_file))
        else:
            output_file = '{}.zb{}'.format(output_file, COMPRESSION_EXTENSIONS[compression])

        if os.path.isfile(output_file) and force is False:
            raise FileExistsError('File exists. Please use --force to overwrite existing archives.')
        elif os.path.isfile(output_file) and force is True:
            os.remove(output_file)
        if not os.path.isdir(input_directory):
            raise NotADirectoryError('Only the archiving of directories is currently supported.')
        if os.path.isdir(output_file):
            raise IsADirectoryError('Cannot specify existing directory as output. Output must be named *.tar.gz file.')

        logging.info('Reading files and calculating checksums.')

        # recursively get a list of files in the input_directory and md5 sum for each file

        try:
            _, filenames = self._scandir(input_directory)
        except Exception as e:
            logging.error(e)
            raise e

        # Generate md5 sums & make JSON relative to input_directory folder
        parent_dir = str(os.path.abspath(os.path.join(input_directory, os.pardir)))
        base_folder = os.path.basename(os.path.normpath(input_directory))

        contents = {}
        
        contents['md5sums'] = {str(file).replace(parent_dir, "").replace(base_folder, PAYLOAD_DIRECTORY): self._md5sum_file(file) for file in filenames}

        # add metadata to contents:
        contents[ZB_VERSION] = CURRENT_ZENODO_BACKPACK_VERSION
        contents[DATA_VERSION] = data_version
        contents[PAYLOAD_DIRECTORY_KEY] = PAYLOAD_DIRECTORY


        # write json to /tmp
        tmpdir = tempfile.TemporaryDirectory()
        contents_json = os.path.join(tmpdir.name, 'CONTENTS.json')
        with open(contents_json, 'w') as c:
            json.dump(contents, c)

        logging.info('Creating archive at: {}'.format(output_file))

        logging.info('Using {} compression at level {}'.format(compression, compression_level))

        if compression == ZSTD:
            compressed = _zstd_open(output_file, 'wb', level=compression_level)
        else:
            compressed = gzip.open(output_file, 'wb', compresslevel=compression_level)

        root_folder_name = f'{base_folder}.zb'

        try:
            # Passing name as well as fileobj lets tarfile skip the output
            # archive if it is inside input_directory.
            with tarfile.open(name=output_file, fileobj=compressed, mode="w|", dereference=True) as archive:
                archive.add(contents_json, os.path.join(root_folder_name, 'CONTENTS.json'))
                archive.add(input_directory, arcname=os.path.join(root_folder_name, PAYLOAD_DIRECTORY))
        finally:
            compressed.close()
            tmpdir.cleanup()

        logging.info('ZenodoBackpack created successfully!')

    def _md5sum_file(self, file):
        """Computes MD5 sum of file.
        Arguments:
            file (str): Path of file to md5sum
        Returns:
            str: md5sum
        """
        block_size = 4096
        m = hashlib.md5()
        with open(file, 'rb') as f:
            while True:
                data = f.read(block_size)
                if not data:
                    return m.hexdigest()
                m.update(data)

    def _scandir(self, dir):
        """Recursively scans directory
        Arguments:
            dir (str): Path of directory to scan
        Returns:
            subfolders: (list) list of all subfolders. Primarily used for recursion.
            files: (list) list of the paths of all files in directory
        """
        subfolders, files = [], []

        for f in os.scandir(dir):
            if f.is_dir():
                subfolders.append(f.path)
            if os.path.islink(f.path):
                #make sure symlink is not broken
                if not os.path.exists(os.path.abspath(f.path)):
                    raise BrokenSymlinkException
                else:
                    files.append(f.path)
            if f.is_file():
                files.append(os.path.abspath(f.path))

        for dir in list(subfolders):
            sf, f = self._scandir(dir)
            subfolders.extend(sf)
            files.extend(f)

        return subfolders, files
