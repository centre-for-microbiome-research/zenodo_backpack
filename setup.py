from setuptools import setup, find_packages

setup(
    name='zenodobackpack',
    version='1.0.0',
    packages=find_packages(),
    url='https://github.com/centre-for-microbiome-research/doi_backpack',
    license='GPL3',
    install_requires=('tqdm',
                      'requests'),
    author='Alex Chklovski',
    scripts=['bin/zenodobackpack'],
    author_email='chklovski@gmail.com',
    description='zenodobackpack = toolkit for Zenodo data integration - downloads zenodo-backformatted data from Zenodo DOI/archives data for upload'
)