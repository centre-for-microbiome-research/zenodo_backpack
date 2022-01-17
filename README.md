# zenodo_backpack

ZenodoBackpack provides a robust, standardised and repeatable approach to
distributing and using backend databases that bioinformatic tools rely on. These
databases are usually tool-specific and are often large enough in size that they
cannot be uploaded as data to software repositories (e.g. PyPI imposes a limit
of ~50MB).

ZenodoBackpack uploads/downloads data to/from [Zenodo](https://zenodo.org),
which means that each dataset is associated with a DOI. Additionally, it
encapsulates the uploaded data in a Zenodo Backpack format, which is really just
a `CONTENTS.json` file and compresses the data in `.tar.gz` format before
upload. The `CONTENTS.json` file includes md5sum values for each included file
for robust verification.

It contains two main methods, which can bee accessed through the
`zenodo_backpack` script or accessed as a software library:

**create**: turns a target directory into a zenodo_backpack-formatted .tar.gz archive with relevant checksum and version information, ready to be uploaded to Zenodo
     
**download_and_extract**: takes a DOI string to download, extract and verify a zenodo_backpack archive from Zenodo.org to target directory. 
    

# Usage

#### Command line
You can run zenodo_backpack as a stand-alone program, or import its classes and use them in source code. 

In command line, zenodo_backpack can create an archive to be uploaded to Zenodo: 

```
zenodo_backpack create --input_directory <./INPUT_DIRECTORY> --data_version <VERSION> --output_file <./ARCHIVE.tar.gz>
```

**NOTE**: it is important that when entering metadata on Zenodo, the version specified **MUST** match that supplied with --data_version

An uploaded existing zenodo_backpack can be downloaded (--bar if a graphical progress bar is desired) and unpacked as follows: 

```
zenodo_backpack download --doi <MY.DOI/111> --output_directory <OUTPUT_DIRECTORY> --bar
```

#### Import

You can also import zenodo_backpack as a module: 

``import zenodo_backpack``

Instantiate the classes by using the appropriate logging level:

``backpack_creator = zenodo_backpack.zenodo_backpack_creator()``

``backpack_downloader = zenodo_backpack.zenodo_backpack_downloader()``

And then utilize them where necessary: 

``backpack_creator.create("/path/to/DIR_DO_BE_ARCHIVED", "path/to/archive.tar.gz", version, force=True)``

``backpack_downloader.download_and_extract('/path/to/download_directory', 'MY.DOI/111111', progress_bar=True, check_version=False)``

Neither class returns anything unless an error is encountered, in which case a relevant Exception is raised. 


# Installation

The easiest way to install is using conda:

```conda install -c bioconda zenodo_backpack```

Alternatively, you can git clone the repository and either run the bin/zenodo_backpack executable or install it with setup tools using 

```python setup.py install```

zenodo_backpack relies on **requests** and **tqdm** to display an optional graphical progress bar. 
