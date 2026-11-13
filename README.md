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

It contains two main methods, which can be accessed through the
`zenodo_backpack` script or accessed as a software library:

**create**: turns a target directory into a zenodo_backpack-formatted .tar.gz archive with relevant checksum and version information, ready to be uploaded to Zenodo. It is necessary to provide a data version when doing so - furthermore, when uploading this backpack to zenodo.org, the version specified on the website **must** match that provided when the ZenodoBackpack was created. This allows version tracking and version validation of the data contained within the ZenodoBackpack. 
     
**download_and_extract**: takes a DOI string to download, extract and verify a zenodo_backpack archive from Zenodo.org to target directory. This returns a ZenodoBackpack object that can be queried for information. 
    

# Usage

## Command line
You can run zenodo_backpack as a stand-alone program, or import its classes and use them in source code. 

In command line, zenodo_backpack can create an archive to be uploaded to Zenodo: 

```
zenodo_backpack create --input_directory <./INPUT_DIRECTORY> --data_version <VERSION> --output_file <./ARCHIVE.tar.gz>
```

**NOTE**: it is important that when entering metadata on Zenodo, the version specified **MUST** match that supplied with --data_version

By default archives are gzip compressed at level 9. zstd compression can be used instead, either with `--compression zstd` or by naming the output file `*.tar.zst`. The compression level can be set with `--compression-level` (gzip: 0-9, default 9; zstd: 1-22, default 3):

```
zenodo_backpack create --input_directory <./INPUT_DIRECTORY> --data_version <VERSION> --output_file <./ARCHIVE.tar.zst> --compression zstd --compression-level 19
```

zstd support requires Python 3.14+ (which has `compression.zstd` built in), or the [zstandard](https://pypi.org/project/zstandard/) package for older Python versions. Downloading auto-detects whether a backpack is gzip or zstd compressed.

An uploaded existing zenodo_backpack can be downloaded (--bar if a graphical progress bar is desired) and unpacked as follows: 

```
zenodo_backpack download --doi <MY.DOI/111> --output_directory <OUTPUT_DIRECTORY> --bar
```

## Mirrors

A backpack can be served from mirrors as well as Zenodo, e.g. a faster institutional server. The Zenodo record stays the authority: it lists the mirrors, and its file name, size, md5sum and version are always enforced, so a broken or out-of-date mirror can never produce a wrong backpack. It just means a fallback to the next source.

To add a mirror:

1. Upload the **exact same** `.tar.gz`/`.tar.zst` file that was uploaded to Zenodo to the mirror. Do not recompress it, or its md5sum will differ.
2. Check the mirror serves the right file before adding it to the record:
   ```
   zenodo_backpack check-mirrors --doi <MY.DOI/111> --mirror https://example.org/path/to/my.zb.tar.gz
   ```
3. Edit the Zenodo record and add a *Related work* entry with relation **Is identical to**, the mirror URL as identifier, and scheme URL. Published records' metadata can be edited without creating a new version, so mirrors can be added or removed at any time. Each version has its own metadata, so add the mirror to every version it serves.
4. Optionally, check the mirrors now listed in the record (add `--version-of-data` for a version other than the newest):
   ```
   zenodo_backpack check-mirrors --doi <MY.DOI/111>
   ```
   `--size-only` compares sizes only, without downloading. `check-mirrors` exits non-zero if any mirror fails.

When downloading, mirrors are tried first, in the order they are listed in the record, then Zenodo. A source is skipped if it is unreachable, reports the wrong size, or serves a file whose md5sum doesn't match the Zenodo record. Use `--no-mirrors` (or `use_mirrors=False` in the API) to download from Zenodo only.

## API Usage

You can also import zenodo_backpack as a module: 

```
import zenodo_backpack
```

Backpacks can be created, downloaded and acquired from a local store:

### Create a backpack

Create a new backpack in `.tar.gz` format containing the payload data folder:
```
creator = zenodo_backpack.ZenodoBackpackCreator()
creator.create("/path/to/payload_directory", "path/to/archive.tar.gz", "0.1")
```

or with zstd compression at a specified level:
```
creator.create("/path/to/payload_directory", "path/to/archive.tar.zst", "0.1", compression="zstd", compression_level=19)
```

### Download a backpack

Download a backpack from Zenodo, defined by the DOI. The version is optional, and if not provided, the latest version will be downloaded. If the target file already exists, the download will resume where possible rather than starting from the beginning.:
```
backpack_downloader = zenodo_backpack.ZenodoBackpackDownloader()
backpack = backpack_downloader.download_and_extract('/path/to/download_directory', 'MY.DOI/111111', version='MY.VERSION')
```

Mirrors listed in the Zenodo record are used in preference to Zenodo (see [Mirrors](#mirrors)); pass `use_mirrors=False` to download only from Zenodo. Mirrors can be checked with:
```
results = backpack_downloader.check_mirrors('MY.DOI/111111', mirrors=['https://example.org/my.zb.tar.gz'])
print([(r.url, r.status, r.detail) for r in results])
```

### Read a backpack that is already downloaded

Defined by a path
```
backpack = zenodo_backpack.acquire(path='/path/to/zenodobackpack/', md5sum=True)
```
or by environment variable
```
backpack = zenodo_backpack.acquire(env_var_name='MY_PROGRAM_DB', version="1.5.2")
```

### Working with a backpack

The `ZenodoBackpack` object returned by `acquire` and `download_and_extract` has instance methods to get at the downloaded data. For example, it can return the path to the payload directory within the `ZenodoBackpack` containing all the payload data:

```
useful_data_path = zenodo_backpack.acquire(env_var_name='MyZenodoBackpack', version="1.5.2").payload_directory_string()
```

# Installation

zenodo_backpack can be installed from pypi:

```
pip install zenodo-backpack
```

The easiest way to install is using conda:

```
conda install -c conda-forge zenodo_backpack
```

Alternatively, you can git clone the repository and either run the bin/zenodo_backpack executable or install it with setup tools using 

```
python setup.py install
```

zenodo_backpack relies on **requests** and **tqdm** to display an optional graphical progress bar. On Python versions before 3.14, zstd support additionally requires **zstandard** (`pip install zenodo-backpack[zstd]`).
