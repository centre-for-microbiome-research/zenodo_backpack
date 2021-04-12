# ZenodoBackpack

The purpose of ZenodoBackpack is to provide a robust and standardised approach to uploading/downloading program data to/from Zenodo. 
It uses a pre-defined ZenodoBackpack data archive with automatic checksum and version verification to simplify installation and creation of new versions. 

ZenodoBackpack relies on **requests** and **tqdm** to display an optional graphical progress bar. 

It contains two main methods:

**create**: turns a target directory into a ZenodoBackpack-formatted .tar.gz archive with relevant checksum and version information, ready to be uploaded to Zenodo
     
**download_and_extract**: takes a DOI string to download, extract and verify a ZenodoBackpack archive from Zenodo.org to target directory. 
    

# Usage

#### Command line
You can run zenodobackpack as a stand-alone program, or import its classes and use them in source code. 

In command line, zenodobackpack can create an archive to be uploaded to Zenodo: 

``zenodobackpack create --input_directory <./INPUT_DIRECTORY> --data_version <VERSION> --output_file <./ARCHIVE.tar.gz>``

**NOTE**: it is important that when entering metadata on Zenodo, the version specified **MUST** match that supplied with --data_version

An uploaded existing ZenodoBackpack can be downloaded (--bar if a graphical progress bar is desired) and unpacked as follows: 

``zenodobackpack download --doi <MY.DOI/111> --output_directory <OUTPUT_DIRECTORY> --bar``

#### Library

You can also import ZenodoBackpack as a library: 

``from ZenodoBackpack import zenodoClasses``

Instantiate the classes by using the appropriate logging level:

``backpackCreater = zenodoClasses.ZenodoBackpackCreator('INFO')``

``backpackDownloader = zenodoClasses.ZenodoBackpack('DEBUG')``

And then utilize them where necessary: 

``backpackCreater.create("/path/to/DIR_DO_BE_ARCHIVED", "path/to/archive.tar.gz", version, force=True)``
``backpackDownloader.download_and_extract('/path/to/download_directory', 'MY.DOI/111111', progress_bar=True, no_check_version=False)``

Neither class returns anything unless an error is encountered, in which case a relevant Exception is raised. 


# Installation

The easiest way to install is using conda:

```conda install -c bioconda zenodobackpack```

Alternatively, you can git clone the repository and either run the bin/zenodobackpack executable or install it with setup tools using 

``python setup.py install``
