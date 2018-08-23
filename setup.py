#!/usr/bin/env python3

import os
from setuptools import setup, find_packages


BASE_DIR = os.path.abspath(os.path.dirname(__file__))
try:
    with open(os.path.join(BASE_DIR, 'README.rst')) as fp:
        README = fp.read()
except IOError:
    README = ''

setup(name='telegram-bot',
      version='0.0.1',
      description='',
      long_description=README,
      classifiers=[
          'Development Status :: 3 - Alpha'
      ],
      keywords='',
      url='https://github.com/dead-beef/telegram-bot',
      author='dead-beef',
      license='MIT',
      packages=find_packages(include=('bot*',)),
      entry_points={
          'console_scripts': ['telegram-bot=bot:cli.main'],
      },
      install_requires=[
          'enum34',
          'python-telegram-bot',
          'pysocks',
          'markovchain>=0.2.0',
          'dice'
      ],
      extras_require={
          'dev': [
              'pytest',
              'pytest-mock',
              'coverage',
              'twine>=1.8.1',
              'wheel'
          ]
      },
      python_requires='>=3',
      include_package_data=True,
      zip_safe=False)
