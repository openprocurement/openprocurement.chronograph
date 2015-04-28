import os

from setuptools import setup, find_packages

here = os.path.abspath(os.path.dirname(__file__))
README = open(os.path.join(here, 'README.rst')).read()
CHANGES = open(os.path.join(here, 'CHANGES.rst')).read()

requires = [
    'setuptools',
    'pyramid',
    'chaussette',
    'gevent',
    'couchdb',
    'apscheduler',
    'requests',
    'iso8601',
    'SQLAlchemy',
    'pysqlite',
    'pyramid_exclog',
    'pbkdf2',
]
test_requires = requires + [
    'webtest',
    'python-coveralls',
]

setup(name='openprocurement.chronograph',
      version='0.3',
      description='openprocurement.chronograph',
      long_description=README + '\n\n' + CHANGES,
      classifiers=[
          "Programming Language :: Python",
          "Framework :: Pyramid",
          "Topic :: Internet :: WWW/HTTP",
          "Topic :: Internet :: WWW/HTTP :: WSGI :: Application",
      ],
      author='',
      author_email='',
      url='',
      keywords='web pyramid pylons',
      packages=find_packages(),
      namespace_packages=['openprocurement'],
      include_package_data=True,
      zip_safe=False,
      install_requires=requires,
      tests_require=test_requires,
      test_suite="openprocurement.chronograph",
      entry_points="""\
      [paste.app_factory]
      main = openprocurement.chronograph:main
      """,
      )
