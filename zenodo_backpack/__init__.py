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

from .version import __version__

class ZenodoBackpackMalformedException(Exception):
    pass  # No implementation needed


class ZenodoBackpackVersionException(Exception):
    pass


class ZenodoConnectionException(Exception):
    pass

class BrokenSymlinkException(Exception):
    pass

CURRENT_ZENODO_BACKPACK_VERSION = 1

PAYLOAD_DIRECTORY_KEY = 'payload_directory'
PAYLOAD_DIRECTORY = 'payload_directory'
DATA_VERSION = 'data_version'
ZB_VERSION = 'zenodo_backpack_version'

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
                ZenodoBackpackDownloader().verify(basefolder)
            return zb

        else:
            raise ZenodoBackpackMalformedException(f"{logging_description} does not contain a CONTENTS.json file, so is not a valid ZenodoBackpack")
    else:
        raise ZenodoBackpackMalformedException(f"{logging_description} is not a directory so cannot hold a ZenodoBackpack")


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

        Returns a ZenodoBackpack object containing the downloaded files
        """
        self._make_sure_path_exists(directory)

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
                for _ in range(download_retries):
                    try:
                        self._download_file(link, os.path.join(directory, filename), progress_bar)
                    except Exception as e:
                        logging.error('Error during download: {}'.format(e))
                        raise ZenodoConnectionException
                    else:
                        break
                else:
                    raise ZenodoConnectionException('Too many unsuccessful retries. Download is aborted')

                #self.verify(acquire(directory), metadata=metadata)
                if self._check_hash(os.path.join(directory, filename), checksum):
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
            zb_folder = os.path.commonprefix(tf.getnames())
            tf.extractall(directory)
            os.remove(filepath)

        os.remove(os.path.join(directory, 'md5sums.txt'))

        zb_folder = os.path.abspath(os.path.join(directory, zb_folder))

        with open(os.path.join(zb_folder, 'CONTENTS.json')) as json_file:
            contents = json.load(json_file)

        zb = ZenodoBackpack(zb_folder)

        if not check_version:
            self.verify(zb)
        else:
            self.verify(zb, metadata=metadata)

        return zb

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
            output_file = os.path.join('{}.zb.tar.gz'.format(str(output_file)))

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

        archive = tarfile.open(os.path.join(output_file), "w|gz", dereference=True)

        root_folder_name = f'{base_folder}.zb'

        archive.add(contents_json, os.path.join(root_folder_name, 'CONTENTS.json'))
        archive.add(input_directory, arcname=os.path.join(root_folder_name, PAYLOAD_DIRECTORY))
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
