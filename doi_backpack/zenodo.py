
class ZenodoBackpackMalformedException(Exception):
    pass # No implementation needed
class ZenodoBackpackVersionException(Exception):
    pass

CURRENT_ZENODO_BACKPACK_VERSION = 1

class ZenodoBackpack:
    def download_and_extract(self, directory, series_doi, version=None):
        """Actually do the download, to a given path. Also extract the archive,
        and then call verify on it.
        
        Parameters
        ----------
        directory: str
            Where to download to
        series_doi: str
            DOI of the Zenodo series
        version: None or int
            If None, the newest version is downloaded. Otherwise int refers to
            the version to be downloaded.

        Returns nothing
        """

        raise NotImplementedError


    def verify(self, directory, series_doi, version=None, check_version=True):
        """Verify that a downloaded directory is in working order.

        Parameters
        ----------
        directory: str
            Where to download to
        series_doi: str
            DOI of the Zenodo series
        version: None or int
            If None, the newest version is required. Otherwise int refers to the
            version expected.
        check_version: True or False
            Check version by querying Zenodo DOI if check_version is True,
            otherwise don't

        Returns nothing if verification works, otherwise raises
        ZenodoBackpackMalformedException or ZenodoBackpackVersionException
        """
        # Read CONTENTS.json file, which lists 
        # * a zenodo_backpack_version
        # * the series_doi
        # * for each file its md5sum

        # Query zenodo to find the available versions
        # Check the version on the CONTENTS.json matches the version parameter

        # Verify the md5sum of each file (except CONTENTS.json itself)
        # raise ZenodoBackpackMalformedException if failed to verify
        raise NotImplementedError


class ZenodoBackpackCreator:
    def create(input_directory, output_file, force=False):
        """Verify that a downloaded directory is in working order.

        Parameters
        ----------
        input_directory: str
            Files to be packaged
        output_file: str
            This method creates this file
        force: True or False
            If True, overwrite an existing output_file if required. If False,
            don't overwrite.

        Returns nothing, unless input_directory is not a directory or
        output_file exists, which raises ZenodoBackpackMalformedException
        """
        # Ensure the output_file ends with .tar.gz
        # get md5sum of each each file, creating a hash

        # Make a tar.gz with a folder containing the input dirctory and
        # CONTENTS.json file. We want to avoid a tar bomb, but I reckon a
        # CONTENTS.json file and the folder is OK enough.
        raise NotImplementedError
        