#!/usr/bin/env python
"""
Twisted Twitter interface.

Copyright (c) 2008  Dustin Sallings <dustin@spy.net>
"""

import time
import base64
import urllib
import mimetypes
import mimetools

from twisted.python import log
from twisted.internet import reactor, defer
from twisted.web import client

import txml

BASE_URL="http://twitter.com"
SEARCH_URL="http://search.twitter.com/search.atom"

class Twitter(object):

    agent="twitty twister"

    def __init__(self, user=None, passwd=None,
        base_url=BASE_URL, search_url=SEARCH_URL):

        self.base_url = base_url
        self.search_Url = search_url
        self.username = user
        self.password = passwd

    def _makeAuthHeader(self, headers=None):
        if not headers:
            headers = {}
        authorization = base64.encodestring('%s:%s'
            % (self.username, self.password))[:-1]
        headers['Authorization'] = "Basic %s" % authorization
        return headers

    def _urlencode(self, h):
        rv = []
        for k,v in h.iteritems():
            rv.append('%s=%s' %
                (urllib.quote(k.encode("utf-8")),
                urllib.quote(v.encode("utf-8"))))
        return '&'.join(rv)

    def __encodeMultipart(self, fields, files):
        """
        fields is a sequence of (name, value) elements for regular form fields.
        files is a sequence of (name, filename, value) elements for data to be uploaded as files
        Return (content_type, body) ready for httplib.HTTP instance
        """
        boundary = mimetools.choose_boundary()
        CRLF = '\r\n'
        l = []
        for k, v in fields:
            l.append('--' + boundary)
            l.append('Content-Disposition: form-data; name="%s"' % k)
            l.append('')
            l.append(v)
        for (k, f, v) in files:
            l.append('--' + boundary)
            l.append('Content-Disposition: form-data; name="%s"; filename="%s"' % (k, f))
            l.append('Content-Type: %s' % self.__getContentType(f))
            l.append('')
            l.append(v)
        l.append('--' + boundary + '--')
        l.append('')
        body = CRLF.join(l)
        return boundary, body

    def __getContentType(self, filename):
        return mimetypes.guess_type(filename)[0] or 'application/octet-stream'

    def __postMultipart(self, path, fields=(), files=()):
        (boundary, body) = self.__encodeMultipart(fields, files)
        h = {'Content-Type': 'multipart/form-data; boundary=%s' % boundary,
            'Content-Length': str(len(body))
            }

        return client.getPage((self.base_url + "%s") % path, method='POST',
            agent=self.agent,
            postdata=body, headers=self._makeAuthHeader(h))

    def __post(self, path, args={}):
        h = {'Content-Type': 'application/x-www-form-urlencoded'}
        return client.getPage((self.base_url + "%s") % path, method='POST',
            agent=self.agent,
            postdata=self._urlencode(args), headers=self._makeAuthHeader(h))

    def __get(self, path, delegate, params, feed_factory=txml.Feed):
        url = self.base_url + path
        if params:
            url += '?' + self._urlencode(params)
        return client.downloadPage(url, feed_factory(delegate),
            agent=self.agent, headers=self._makeAuthHeader())

    def verify_credentials(self):
        "Verify a user's credentials."
        return self.__post("/account/verify_credentials.xml")

    def __parsed_post(self, hdef, parser):
        deferred = defer.Deferred()
        hdef.addErrback(lambda e: deferred.errback(e))
        hdef.addCallback(lambda p: deferred.callback(parser(p)))
        return deferred

    def update(self, status, source=None):
        "Update your status.  Returns the ID of the new post."
        params={'status': status}
        if source:
            params['source'] = source
        return self.__parsed_post(self.__post("/statuses/update.xml", params),
            txml.parseUpdateResponse)

    def friends(self, delegate, params={}):
        """Get updates from friends.

        Calls the delgate once for each status object received."""
        return self.__get("/statuses/friends_timeline.xml", delegate, params,
            txml.StatusList)

    def user_timeline(self, delegate, user=None, params={}):
        """Get the most recent updates for a user.

        If no user is specified, the statuses for the authenticating user are
        returned.

        See search for example of how results are returned."""
        if user:
            params['id'] = user
        return self.__get("/statuses/user_timeline.atom", delegate, params)

    def public_timeline(self, delegate, params={}):
        "Get the most recent public timeline."

        return self.__get("/statuses/public_timeline.atom", delegate, params)

    def direct_messages(self, delegate, params={}):
        """Get direct messages for the authenticating user.

        Search results are returned one message at a time a DirectMessage
        objects"""
        return self.__get("/direct_messages.xml", delegate, params, txml.Direct)

    def replies(self, delegate, params={}):
        """Get the most recent replies for the authenticating user.

        See search for example of how results are returned."""
        return self.__get("/statuses/replies.atom", delegate, params)

    def follow(self, user):
        """Follow the given user.

        Returns no useful data."""
        return self.__post('/friendships/create/%s.xml' % user)

    def leave(self, user):
        """Stop following the given user.

        Returns no useful data."""
        return self.__post('/friendships/destroy/%s.xml' % user)

    def list_friends(self, delegate, user=None, params=None):
        """Get the list of friends for a user.

        Calls the delegate with each user object found."""
        if user:
            url = self.base_url + '/statuses/friends/' + user + '.xml'
        else:
            url = self.base_url + '/statuses/friends.xml'
        if params:
            url += '?' + self._urlencode(params)
        return client.downloadPage(url, txml.Users(delegate),
            headers=self._makeAuthHeader())

    def list_followers(self, delegate, user=None, params=None):
        """Get the list of followers for a user.

        Calls the delegate with each user object found."""
        if user:
            url = self.base_url + '/statuses/followers/' + user + '.xml'
        else:
            url = self.base_url + '/statuses/followers.xml'
        if params:
            url += '?' + self._urlencode(params)
        return client.downloadPage(url, txml.Users(delegate),
            headers=self._makeAuthHeader())

    def show_user(self, user):
        """Get the info for a specific user.

        Returns a delegate that will receive the user in a callback."""

        d = defer.Deferred()
        if self.username and self.password:
            h = self._makeAuthHeader()
        else:
            h = {}
        url = '%s/users/show/%s.xml' % (self.base_url, user)
        client.downloadPage(url, txml.Users(lambda u: d.callback(u)),
            headers={}).addErrback(lambda e: d.errback(e))
        return d

    def search(self, query, delegate, args=None):
        """Perform a search query.

        Results are given one at a time to the delegate.  An example delegate
        may look like this:

        def exampleDelegate(entry):
            print entry.title"""
        if args is None:
            args = {}
        args['q'] = query
        return client.downloadPage(SEARCH_URL + '?' + self._urlencode(args),
            txml.Feed(delegate), agent=self.agent)

    def block(self, user):
        """Block the given user.

        Returns no useful data."""
        return self.__post('/blocks/create/%s.xml' % user)

    def unblock(self, user):
        """Unblock the given user.

        Returns no useful data."""
        return self.__post('/blocks/destroy/%s.xml' % user)

    def update_profile_image(self, filename, image):
        """Update the profile image of an authenticated user.
        The image parameter must be raw data.

        Returns no useful data."""

        return self.__postMultipart('/account/update_profile_image.xml', files=(('image', filename, image),))

class TwitterFeed(Twitter):
    """Realtime feed handling class.

    Results are given one at a time to the delegate.  An example delegate
    may look like this:

    def exampleDelegate(entry):
        print entry.text"""

    def _rtfeed(self, url, delegate, args):
        if args:
            url += "?" + self._urlencode(args)
        print "Fetching", url
        return client.downloadPage(url, txml.HoseFeed(delegate), agent=self.agent,
                                   headers=self._makeAuthHeader())

    def spritzer(self, delegate, args=None):
        """Get the spritzer feed."""
        return self._rtfeed("http://stream.twitter.com/spritzer.xml", delegate, args)

    def gardenhose(self, delegate, args=None):
        """Get the gardenhose feed."""
        return self._rtfeed("http://stream.twitter.com/gardenhose.xml", delegate, args)

    def firehose(self, delegate, args=None):
        """Get the firehose feed."""
        return self._rtfeed("http://stream.twitter.com/firehose.xml", delegate, args)
