from setuptools import setup, find_packages

setup(
    name='nfl_stats',
    version='1.0.0',
    description='Scraping data from pro-football-reference.com and other sites',
    url='https://github.com/awgymer/pfr-scrape',
    author='Arthur Gymer',
    packages=find_packages(),
    install_requires=[
        'appdirs',
        'boltons',
        'mementos',
        'numpy',
        'pandas',
        'pyquery',
        'requests',
    ]
)
