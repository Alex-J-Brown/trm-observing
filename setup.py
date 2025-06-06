from setuptools import setup
from setuptools.extension import Extension

setup(name='trm.observing',
      version='1.1.6',
      packages = ['trm', 'trm.observing'],
      scripts=['scripts/eplanner.py', 'scripts/parallactic.py'],

      # metadata
      author='Tom Marsh',
      author_email='t.r.marsh@warwick.ac.uk',
      description="Python observing utility module",
      url='http://www.astro.warwick.ac.uk/',
      long_description="""
observing mainly provides a script to help schedule eclipses along
with a few classes to help other build other scripts that need to use
the position / ephemeris files.
""",

      )

