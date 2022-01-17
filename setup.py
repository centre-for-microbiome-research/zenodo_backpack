from setuptools import setup, find_packages

with open('README.md') as readme_file:
    readme = readme_file.read()

exec(open('zenodo_backpack/version.py').read()) # loads __version__

setup(
    name='zenodo_backpack',
    version=__version__,
    packages=find_packages(),
    url='https://github.com/centre-for-microbiome-research/zenodo_backpack',
    license='GPL3+',
    install_requires=('tqdm',
                      'requests'),
    author=['Alex Chklovski','Ben Woodcroft'],
    scripts=['bin/zenodo_backpack'],
    author_email='chklovski@gmail.com',
    description='Manage data bundled with bioinformatic software through Zenodo DOI integration',
    long_description=readme,
    long_description_content_type='text/markdown',
    classifiers=[
        # How mature is this project? Common values are
        #   3 - Alpha
        #   4 - Beta
        #   5 - Production/Stable
        'Development Status :: 3 - Alpha',
        # Indicate who your project is intended for
        'Topic :: Scientific/Engineering',
        'Topic :: Scientific/Engineering :: Bio-Informatics',
        # Pick your license as you wish (should match "license" above)
        'License :: OSI Approved :: GNU General Public License v3 or later (GPLv3+)',
        # Specify the Python versions you support here. In particular, ensure
        # that you indicate whether you support Python 2, Python 3 or both.
        'Programming Language :: Python :: 3',
    ],
)