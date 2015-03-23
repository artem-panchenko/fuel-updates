#    Copyright 2015 Mirantis, Inc.
#
#    Licensed under the Apache License, Version 2.0 (the "License"); you may
#    not use this file except in compliance with the License. You may obtain
#    a copy of the License at
#
#         http://www.apache.org/licenses/LICENSE-2.0
#
#    Unless required by applicable law or agreed to in writing, software
#    distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
#    WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
#    License for the specific language governing permissions and limitations
#    under the License.


import logging
import os
import re
import subprocess
import zlib

from optparse import OptionParser
from urllib2 import urlopen
from urllib2 import HTTPError
from urlparse import urlparse
from xml.dom.minidom import parseString

logger = logging.getLogger(__name__)


class Settings(object):
    supported_distros = ('centos', 'ubuntu')
    supported_releases = ('2014.2-6.1')
    updates_destinations = {
        'centos': r'/var/www/nailgun/{0}/centos/updates',
        'ubuntu': r'/var/www/nailgun/{0}/ubuntu/updates'
    }


class UpdatePackagesException(Exception):
    pass


def exec_cmd(cmd):
    logger.debug('Execute command "%s"', cmd)
    child = subprocess.Popen(
        cmd, stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        shell=True)

    logger.debug('Stdout and stderr of command "%s":', cmd)
    for line in child.stdout:
        logger.debug(line.rstrip())

    return _wait_and_check_exit_code(cmd, child)


def _wait_and_check_exit_code(cmd, child):
    child.wait()
    exit_code = child.returncode
    logger.debug('Command "%s" was executed', cmd)
    return exit_code


def get_repository_packages(remote_repo_url, distro):
    repo_url = urlparse(remote_repo_url)
    packages = []
    if distro in ('ubuntu',):
        packages_url = '{0}/Packages'.format(repo_url.geturl())
        pkgs_raw = urlopen(packages_url).read()
        for pkg in pkgs_raw.split('\n'):
            match = re.search(r'^Package: (\S+)\s*$', pkg)
            if match:
                packages.append(match.group(1))
    elif distro in ('centos',):
        packages_url = '{0}/repodata/primary.xml.gz'.format(repo_url.geturl())
        pkgs_xml = parseString(zlib.decompressobj(zlib.MAX_WBITS | 32).
                               decompress(urlopen(packages_url).read()))
        for pkg in pkgs_xml.getElementsByTagName('package'):
            packages.append(
                pkg.getElementsByTagName('name')[0].firstChild.nodeValue)
    return packages


def mirror_remote_repository(remote_repo_url, local_repo_path):
    repo_url = urlparse(remote_repo_url)
    cut_dirs = len(repo_url.path.strip('/').split('/'))
    download_cmd = ('wget --recursive --no-parent --no-verbose --reject "index'
                    '.html*,*.gif" --exclude-directories "{pwd}/repocache" '
                    '--directory-prefix {path} -nH --cut-dirs={cutd} {url}').\
        format(pwd=repo_url.path.rstrip('/'), path=local_repo_path,
               cutd=cut_dirs, url=repo_url.geturl())
    if exec_cmd(download_cmd) != 0:
        raise UpdatePackagesException('Mirroring of remote packages'
                                      ' repository failed!')


def main():
    settings = Settings()

    sh = logging.StreamHandler()
    formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
    sh.setFormatter(formatter)
    logger.addHandler(sh)
    logger.setLevel(logging.INFO)

    parser = OptionParser(
        description="Pull updates for a given release of Fuel based on "
                    "the provided URL."
    )
    parser.add_option('-d', '--distro', dest='distro', default=None,
                      help='Linux distribution name (required)')
    parser.add_option('-r', '--release', dest='release', default=None,
                      help='Fuel release name (required)')
    parser.add_option("-u", "--url", dest="url", default="",
                      help="Remote repository URL (required)")
    parser.add_option("-v", "--verbose",
                      action="store_true", dest="verbose", default=False,
                      help="Enable debug output")

    (options, args) = parser.parse_args()

    if options.verbose:
        logger.setLevel(logging.DEBUG)

    if options.distro not in settings.supported_distros:
        raise UpdatePackagesException(
            'Linux distro "{0}" is not supported. Please specify one of the '
            'following: "{1}". See help (--help) for details.'.format(
                options.distro, ', '.join(settings.supported_distros)))

    if options.release not in settings.supported_releases:
        raise UpdatePackagesException(
            'Fuel release "{0}" is not supported. Please specify one of the '
            'following: "{1}". See help (--help) for details.'.format(
                options.release, ', '.join(settings.supported_releases)))

    if 'http' not in urlparse(options.url):
        raise UpdatePackagesException(
            'Repository url "{0}" does not look like valid URL. '
            'See help (--help) for details.'.format(options.url))

    updates_path = settings.updates_destinations[options.distro].format(
        options.release)
    if not os.path.exists(updates_path):
        os.makedirs(updates_path)

    logger.info('Checking remote repository...')
    try:
        pkgs = get_repository_packages(options.url, options.distro)
    except HTTPError as e:
        if e.code == 404:
            raise UpdatePackagesException(
                'Remote repository does not contain packages'
                ' metadata ({0})!'.format(options.distro))
        else:
            raise
    if len(pkgs) < 1:
        raise UpdatePackagesException('Remote "{0}" repository does not '
                                      'contain any packages.')
    logger.debug('Remote repository contains next packages: {0}'.format(pkgs))
    logger.info('Started mirroring remote repository...')
    mirror_remote_repository(options.url, updates_path)
    logger.info('Remote repository "{url}" for "{release}" ({distro}) was '
                'successfuly mirrored to {path} folder.'.format(
                    url=options.url,
                    release=options.release,
                    distro=options.distro,
                    path=updates_path))


if __name__ == '__main__':
    main()
