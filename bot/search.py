import os
import re
import json
import hashlib
import logging
from time import time, sleep
from threading import Lock
from collections import defaultdict
from urllib.parse import urlsplit, urlencode

import urllib3
from urllib3.contrib.socks import SOCKSProxyManager

from .error import SearchError


def get_proxy_manager(proxy):
    if not proxy:
        return urllib3.PoolManager()
    if proxy.startswith('socks'):
        return SOCKSProxyManager(proxy)
    return urllib3.ProxyManager(proxy)

def get_referer(url):
    split_url = urlsplit(url)
    return '%s://%s/' % (split_url.scheme, split_url.netloc)

def request(http, method, url, **kwargs):
    ret = http.request(method, url, **kwargs)
    if ret.status != 200:
        raise urllib3.exceptions.ResponseError(
            '%r: response status %d' % (url, ret.status)
        )
    return ret.data


class Search:
    DEFAULT_USER_AGENT = 'Mozilla/5.0 (Windows NT 6.1; rv:60.0) Gecko/20100101 Firefox/60.0'

    def __init__(self, throttle=1, proxy=None, headers=None):
        if headers is None:
            headers = {}
        if 'User-Agent' not in headers:
            headers['User-Agent'] = self.DEFAULT_USER_AGENT
        self.lock = Lock()
        self.logger = logging.getLogger(__name__)
        self.last_used = time()
        self.http = get_proxy_manager(proxy)
        self.headers = headers
        self.throttle = throttle
        self.cache = defaultdict(SearchResults)

    def _request_json(self, results, url, fields=None):
        self.logger.info('request search json %s %r', url, fields)
        data = request(self.http, 'GET', url,
                       headers=self.headers, fields=fields)
        data = json.loads(data.decode('utf-8'))

        try:
            results.next_url = 'https://duckduckgo.com/%s&%s' % (
                data['next'],
                urlencode({'vqd': next(iter(data['vqd'].values()))})
            )
        except (KeyError, StopIteration):
            results.next_url = None
            results.full = True

        results.full = True #

        for i, res in enumerate(data['results'], len(results.items)):
            try:
                res = SearchResult(i, res['thumbnail'], res['image'],
                                   res['url'], res['title'])
                results.items.append(res)
            except KeyError as ex:
                self.logger.warning('results: %r: %r', ex, res)

    def _request(self, query):
        results = self.cache[query]
        self.headers['Referer'] = 'https://duckduckgo.com/'
        if results.next_url is None:
            data = request(
                self.http,
                'GET',
                'https://duckduckgo.com',
                headers=self.headers,
                fields={
                    'q': query,
                    'ia': 'images',
                    'iar': 'images',
                    'iax': 'images'
                }
            ).decode('utf-8')
            vqd = re.search(r'vqd=[\'"]([^\'"]+)[\'"]', data)
            if vqd is None:
                raise urllib3.exceptions.ResponseError('no vqd in response')
            vqd = vqd.group(1)
            url = 'https://duckduckgo.com/i.js'
            fields = {
                'q': query,
                'vqd': vqd,
                'l': 'us-en',
                'o': 'json',
                'f': ',,,',
                'p': '-1'
            }
        else:
            url = results.next_url
            fields = None
        self._request_json(results, url, fields)

    def _throttle(self):
        dt = time() - self.last_used
        if dt < self.throttle:
            sleep(self.throttle - dt)
        self.last_used = time()

    def __getitem__(self, query):
        query = query.strip().lower()
        return self.cache[query]

    def __call__(self, query, offset):
        with self.lock:
            self._throttle()
            query = query.strip().lower()
            results = self.cache[query]
            while True:
                try:
                    self.logger.info('get next result %r', query)
                    ret = results[offset]
                    break
                except IndexError:
                    if results.full:
                        if not results.items:
                            self.logger.info('no results')
                            raise SearchError('no search results')
                        self.logger.info('no more results')
                        ret = results[-1]
                        break
                    else:
                        self.logger.info('request more results')
                        self._request(query)
            is_last = results.full and offset >= len(results) - 1
            return ret, is_last


class SearchResults:
    def __init__(self, results=None, full=False, next_url=None):
        self.items = results if results is not None else []
        self.full = full
        self.next_url = next_url

    def __len__(self):
        return len(self.items)

    def __getitem__(self, i):
        return self.items[i]


class SearchResult:
    def __init__(self, offset, thumbnail, image, url, title):
        self.offset = offset
        self.thumbnail = thumbnail
        self.image = image
        self.title = title
        self.url = url
        self.filename = hashlib.md5(self.thumbnail.encode('utf-8')).hexdigest()

    def __repr__(self):
        return 'SearchResult(%r, %r, %r, %r)' % (
            self.thumbnail,
            self.image,
            self.url,
            self.title
        )

    __str__ = __repr__

    def download(self, http, dir_='/tmp', headers=None):
        fname = os.path.join(dir_, self.filename)
        if os.path.exists(fname):
            return
        if headers is None:
            headers = {}
        url = self.image
        headers['Referer'] = get_referer(url)
        data = request(http, 'GET', url, headers=headers)
        with open(fname, 'wb') as fp:
            fp.write(data)
