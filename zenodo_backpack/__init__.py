import hashlib
import requests
import shutil
import os
import logging
import json
from tqdm import tqdm
import tarfile
import tempfile

from .version import __version__

class ZenodoBackpackMalformedException(Exception):
    pass  # No implementation needed


class ZenodoBackpackVersionException(Exception):
    pass


class ZenodoConnectionException(Exception):
    pass


CURRENT_ZENODO_BACKPACK_VERSION = 1

PAYLOAD_DIRECTORY_KEY = 'payload_directory'

class ZenodoBackpack:
    def __init__(self, base_directory):
        self.base_directory = base_directory
        self.contents = json.load(os.path.join(base_directory, 'CONTENTS.json'))

    def payload_directory_string(self):
        return os.path.join(self.base_directory, self.contents[PAYLOAD_DIRECTORY_KEY])


class ZenodoBackpackDownloader:

    def download_and_extract(self, directory, doi, check_version=True, progress_bar=False, download_retries=3):
        """Actually do the download, to a given path. Also extract the archive,
        and then call verify on it.

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
            Number of download attempts
        Returns nothing
        """

        # get record via DOI, then read in json metadata from records_url
        if doi is not None:

            recordID = self._retrieve_record_ID(doi)
            metadata, files = self._retrieve_record_metadata(recordID)

            # create md5sums file for download
            with open(os.path.join(directory, 'md5sums.txt'), 'wt') as md5file:
                for file in files:
                    fname = str(file['key']).split('/')[-1]
                    checksum = str(file['checksum']).split(':')[-1]
                    md5file.write('{},{}\n'.format(checksum, fname))

            for f in files:
                link = f['links']['self']
                filename = f['key'].split('/')[-1]
                checksum = f['checksum']

                # 3 retries
                for _ in range(3):
                    try:
                        self._download_file(link, os.path.join(directory, filename), progress_bar)
                    except Exception as e:
                        logging.error('Error during download: {}'.format(e))
                        raise ZenodoConnectionException
                    else:
                        break
                else:
                    raise ZenodoConnectionException('Too many unsuccessful retries. Download is aborted')

                if self._check_hash(filename, checksum):
                    logging.debug('Correct checksum for downloaded file.')
                else:
                    raise ZenodoBackpackMalformedException(
                        f"Checksum is incorrect for downloaded file '{filename}'. Please download again.")
            else:
                logging.debug('All files have been downloaded.')

        else:
            raise ZenodoConnectionException('Record could not get accessed.')

        # unzip
        # use md5sums.txt file created from metadata to get files
        downloaded_files = [[str(i) for i in line.strip().split(',')] for line in
                            open(os.path.join(directory, 'md5sums.txt'), 'r').readlines()]
        zipped_files = [item for sublist in downloaded_files for item in sublist if '.tar.gz' in item]

        logging.info('Extracting files from archive...')
        for f in zipped_files:
            filepath = (os.path.join(directory, f))
            logging.debug('Extracting {}'.format(filepath))
            tf = tarfile.open(filepath)
            tf.extractall(directory)
            os.remove(filepath)

        os.remove(os.path.join(directory, 'md5sums.txt'))

        if no_check_version:
            self.verify(directory)
        else:
            self.verify(directory, metadata)

        # os.remove(os.path.join(directory, 'CONTENTS.json'))

    def verify(self, directory, metadata=None):
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

        Returns nothing if verification works, otherwise raises
        ZenodoBackpackMalformedException or ZenodoBackpackVersionException
        """

        try:
            with open(os.path.join(directory, 'CONTENTS.json')) as json_file:
                contents = json.load(json_file)
        except:
            raise ZenodoBackpackMalformedException('Failed to load CONTENTS.json')

        # pop identifying keys for version and zenodo_backpack_version
        version = contents.pop('version')
        zenodo_backpack_version = contents.pop('zenodo_backpack_version')

        if metadata is not None:
            logging.info('Verifying version and checksums...')
            if str(version).strip() != str(metadata['metadata']['version']).strip():
                raise ZenodoBackpackMalformedException(
                    'Version in CONTENTS.json does not match version in Zenodo metadata.')
        else:
            logging.warning('Not using zenodo metadata verification.')
            logging.info('Verifying checksums...')

        if zenodo_backpack_version != CURRENT_ZENODO_BACKPACK_VERSION:
            raise ZenodoBackpackVersionException('Incorrect ZENODO Backpack version: {} Expected: {}'
                                                 .format(zenodo_backpack_version, CURRENT_ZENODO_BACKPACK_VERSION))

        # The rest of contents should only be files with md5 sums.

        for payload_file in contents.keys():
            filepath = os.path.join(directory, payload_file)
            if not self._check_hash(filepath, contents[payload_file], metadata=False):
                raise ZenodoBackpackMalformedException('Extracted file md5 sum does not match that in JSON file.')

        logging.info('Verification success.')

    def _retrieve_record_ID(self, doi):
        """Parses provided DOI retrieve associated Zenodo URL which also contains record ID
        Arguments:
            DOI (str): published DOI associated with file uploaded to Zenodo
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

    def _retrieve_record_metadata(self, recordID):
        """Parses provided recordID to access Zenodo API records and download metadata json
        Arguments:
            recordID (str): Zenodo record number
        Returns:
            js (json object): json metadata file retrieved from Zenodo API.
            js['files'] (list): list of files associated with recordID in question
        """
        records_url = 'https://zenodo.org/api/records/'

        try:
            r = requests.get(records_url + recordID, timeout=15.)
        except Exception as e:
            raise ZenodoConnectionException('Error during metadata retrieval: {}'.format(e))

        if r.ok:
            js = json.loads(r.text)
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
            return value, 'invalid'
        h = hashlib.new(algorithm)
        with open(filename, 'rb') as f:
            while True:
                data = f.read(4096)
                if not data:
                    break
                h.update(data)
        digest = h.hexdigest()
        return value == digest

    def _download_file(self, file_url, out_file, progress_bar=False):
        """Download a file to disk
        Streams a file from URL to disk.
        Can optionally use tqdm for a visual download bar
        Arguments:
            file_url (str): URL of file to download
            out_file (str): Target file path
            progress_bar (bool): Display graphical progresss bar
        """
        if progress_bar:
            logging.info('Downloading {} to {}.'.format(file_url, out_file))
            response = requests.get(file_url, stream=True)
            total_size_in_bytes = int(response.headers.get('content-length', 0))
            block_size = 1024
            progress_bar = tqdm(total=total_size_in_bytes, unit='iB', unit_scale=True)
            with open(out_file, 'wb') as file:
                for data in response.iter_content(block_size):
                    progress_bar.update(len(data))
                    file.write(data)
            progress_bar.close()

        else:
            with requests.get(file_url, stream=True) as r:
                with open(out_file, 'wb') as f:
                    shutil.copyfileobj(r.raw, f)

    def _extract_all(self, archive, extract_path):
        for filename in archive:
            shutil.unpack_archive(filename, extract_path)

    def acquire(self, path=None, env_var_name=None, md5sum=False):
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
                logging.error(f'Could not find requested environmental variable {env_var_name}. Please check it exists.')
                raise ZenodoBackpackMalformedException()
            else:
                basefolder = os.environ[env_var_name]
        else:
            raise ZenodoBackpackMalformedException()

        if os.path.isdir(basefolder):
            if 'CONTENTS.json' in os.listdir(basefolder):
                logging.info('Retrieval successful. Location of backpack is: {}'.format(basefolder))

                if md5sum:
                    self.verify(basefolder)

                return basefolder
            else:
                raise ZenodoBackpackMalformedException(f"{logging_description} does not contain a CONTENTS.json file, so is not a valid ZenodoBackpack")
        else:
            raise ZenodoBackpackMalformedException(f"{logging_description} is not a directory so cannot hold a ZenodoBackpack")

        raise Exception("Error: acquire requires either a path or an environment variable to be specified")


class ZenodoBackpackCreator:

    def create(self, input_directory, output_file, data_version, force=False):

        """Creates Zenodo backpack

                Parameters:
        ----------
        input_directory: str
            Files to be packaged
        output_file: str
            Archive .tar.gz to be created. Automatically appends '.tar.gz' if needed
        force: True or False
            If True, overwrite an existing output_file if required. If False,
            don't overwrite.
        data_version:
            Passes the data version of the file to archive

                NOTE!! Same version must be specified in Zenodo metadata when file is uploaded, else error.

        Returns nothing, unless input_directory is not a directory or output_file exists, which raises Exceptions
        """

        if not str(output_file).endswith('.tar.gz'):
            output_file = os.path.join('{}.tar.gz'.format(str(output_file)))

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

        contents = {str(file).replace(parent_dir, ""): self._md5sum_file(file) for file in filenames}

        # add metadata to contents:
        contents['zenodo_backpack_version'] = CURRENT_ZENODO_BACKPACK_VERSION
        contents['version'] = data_version

        # write json to /tmp
        tmpdir = tempfile.TemporaryDirectory()
        contents_json = os.path.join(tmpdir.name, 'CONTENTS.json')
        with open(contents_json, 'w') as c:
            json.dump(contents, c)

        logging.info('Creating archive at: {}'.format(output_file))

        archive = tarfile.open(os.path.join(output_file), "w|gz")
        archive.add(contents_json, 'CONTENTS.json')
        archive.add(input_directory, arcname=base_folder)
        archive.close()
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
            if f.is_file():
                files.append(f.path)

        for dir in list(subfolders):
            sf, f = self._scandir(dir)
            subfolders.extend(sf)
            files.extend(f)

        return subfolders, files
