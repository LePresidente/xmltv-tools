# /usr/bin/env python

"""
Original Author:
xmltv-proc-nz by Hadley Rich <hads@nice.net.nz> "https://github.com/hadleyrich/xmltv-tools"
Contributions by Aaron Pelly <aaron@pelly.co>  "https://github.com/apelly/xmltv-tools"
Licensed under the BSD License.

Modified by Lepresidente
ChangeLog:
* Use Redis to store found items to reduce load on api on reruns
* Dropped tvdb due to api changes
* fixed xmltv support using the latest standard
* Some code cleanup and dead code removal
* Updated to use environment variables for docker support
* Image downloads are threaded in the background
"""

# TODO: Find repeats
# TODO: Regex replacements for categories

import redis
import requests
import multiprocessing
import os
import sys
import logging
import threading
import time
import io
import re
from pathlib import Path
from xml.etree import cElementTree as ElementTree
from datetime import timedelta, tzinfo
from optparse import OptionParser
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8",
                              errors='replace')

NAME = 'enhance'
VERSION = '0.0.2'
TIME_FORMAT = '%Y%m%d%H%M%S'
threadcount = multiprocessing.cpu_count() * 2
log = logging.getLogger(NAME)
logging.basicConfig(level=logging.WARNING, format='%(message)s')
downloadlist = []

# Variables
REDIS_HOST = os.getenv('REDIS_HOST', "localhost")
REDIS_PORT = os.getenv('REDIS_PORT', 6379)
REDIS_PASS = os.getenv('REDIS_PASS', "")
TMDB_API = os.getenv('TMDB_API', None)


r = redis.Redis(
    host=REDIS_HOST,
    port=REDIS_PORT,
    password=REDIS_PASS)

try:
    import tmdbv3api
except ImportError:
    log.warning("Failed to import tmdbv3api module.")
    tmdbcheck = False
else:
    tmdbcheck = True


class UTC(tzinfo):
    """
    Represents the UTC timezone
    """

    def utcoffset(self, dt):
        return timedelta(0)

    def tzname(self, dt):
        return "UTC"

    def dst(self, dt):
        return timedelta(0)


class LocalTimezone(tzinfo):
    """
    Represents the computers local timezone
    """

    def __init__(self):
        self.STDOFFSET = timedelta(seconds=-time.timezone)
        if time.daylight:
            self.DSTOFFSET = timedelta(seconds=-time.altzone)
        else:
            self.DSTOFFSET = self.STDOFFSET

        self.DSTDIFF = self.DSTOFFSET - self.STDOFFSET
        tzinfo.__init__(self)

    def utcoffset(self, dt):
        if self._isdst(dt):
            return self.DSTOFFSET
        else:
            return self.STDOFFSET

    def dst(self, dt):
        if self._isdst(dt):
            return self.DSTDIFF
        else:
            return timedelta(0)

    def tzname(self, dt):
        return time.tzname[self._isdst(dt)]

    def _isdst(self, dt):
        tt = (dt.year, dt.month, dt.day, dt.hour, dt.minute, dt.second,
              dt.weekday(), 0, -1)
        stamp = time.mktime(tt)
        tt = time.localtime(stamp)
        return tt.tm_isdst > 0


localtz = LocalTimezone()
utc = UTC()


class BaseProcessor(object):
    valid = True

    def __call__(self, programme):
        raise NotImplementedError

    def post_process(self, programmes):
        raise NotImplementedError


class Movies(BaseProcessor):
    """
    Augment movies with data from themoviedb.com
    """

    def __init__(self):
        if not tmdbcheck:
            self.valid = False
            log.warning('Movies: TMDB module not found.')
            return

        if TMDB_API is None:
            self.valid = False
            log.critical("TMDB API key missing")
            sys.exit(1)

        log.debug("Using TMDB API key %s", TMDB_API)
        tmdb = tmdbv3api.TMDb()
        tmdb.api_key = TMDB_API
        tmdb.language = 'en'

    def __call__(self, programme):
        if not self.valid:
            return

        # try:
        start = programme.get('start')
        stop = programme.get('stop')
        title = programme.find('title').text
        channel = programme.get('channel')
        # except:
        #    log.debug('Movies: Ignoring invalid programme')
        #    return
        if stop is None:
            return
        # Unfortunately strptime can't handle numeric timezones so we strip it.
        # It's only for getting possible movies so won't matter too much.
        if ' ' in start:
            start = start.split(' ')[0]
        if ' ' in stop:
            stop = stop.split(' ')[0]
        start_time = time.mktime(time.strptime(start, TIME_FORMAT))
        stop_time = time.mktime(time.strptime(stop, TIME_FORMAT))
        duration = stop_time - start_time
        # always look up things in the movie category. try to identify others
        # by duration/channel/title
        MovieCat = False
        for cat in programme.findall('category'):
            if cat.text != "movie":
                MovieCat = True
        if not MovieCat:
            # Between 90 mins and 4 hours
            if duration <= 5400 or duration > 14400:
                return

        log.debug('Movies: Possible movie "%s" (duration %dm) on channel "%s"',
                  title, duration / 60, channel)

        movie = None
        movie_title = None
        movie_runtime = None
        movie_posterurl = None
        movie_overview = None
        movie_genres = None
        genres_list = None

        if r.get('movies.{}.title'.format(title.replace(" ", "_"))):
            movie_title = r.get('movies.{}.title'.format(title.replace(" ",
                                "_"))).decode('utf-8')
            if movie_title == "NotFound":
                log.debug('Movies: Ignored "%s" due to being set to NotFound '
                          'on tmdb', title)
                return
            if movie_title == "Multiples":
                log.debug('Movies: Ignored "%s" due to multiple results on '
                          'tmdb', title)
                return
            else:
                movie_runtime = r.get('movies.{}.runtime'.format(
                                      title.replace(" ", "_"))).decode('utf-8')
                if r.get('movies.{}.poster'.format(title.replace(" ", "_"))):
                    movie_posterurl = r.get('movies.{}.poster'.format(
                                            title.replace(" ", "_"))
                                            ).decode('utf-8')
                movie_overview = r.get('movies.{}.overview'.format(
                                       title.replace(" ", "_"))
                                       ).decode('utf-8')
                if r.get('movies.{}.genres'.format(title.replace(" ", "_"))):
                    movie_genres = r.get('movies.{}.genres'.format(
                        title.replace(" ", "_"))).decode('utf-8')
                log.debug('Movies: Redis hit for "%s"', title)
        else:
            try:
                movietmdb = tmdbv3api.Movie()
                results = movietmdb.search(title.replace('?', ''))
            except tmdbv3api.tmdb.TMDbException:
                log.exception('Movies: TMDB problem searching')
                return
            matches = []
            for result in results:
                if result is not None:
                    if normalise_title(title) == normalise_title(result.title):
                        matches.append(result)
            log.debug('Movies: Exact title matches: %d', len(matches))
            for movie in matches:
                try:
                    moviedetails = movietmdb.details(movie.id)
                except tmdbv3api.tmdb.TMDbException:
                    log.exception('Movies: TMDB problem fetching info')
                    return
                if moviedetails.release_date is None:
                    log.debug('Movies: Found match "%s"', moviedetails.title)
                else:
                    log.debug('Movies: Found match "%s" (%s)', moviedetails.title, moviedetails.release_date)
            if len(matches) == 1:
                try:
                    log.debug('Movies: Cache miss for "%s"', title)
                    movie = movietmdb.details(matches[0].id)
                except tmdbv3api.tmdb.TMDbException:
                    log.exception('Movies: TMDB problem fetching info')
                    return
                movie_title = movie.title
                movie_runtime = movie.runtime
                if movie.poster_path is not None:
                    tmdbconfiguration = tmdbv3api.Configuration()
                    base_url = tmdbconfiguration.info().images['base_url']
                    movie_posterurl = base_url + "w342" + movie.poster_path
                    r.set('movies.{}.poster'.format(title.replace(" ", "_")),
                          movie_posterurl)
                    r.expire('movies.{}.poster'.format(title.replace(" ", "_")
                                                       ), 60 * 60 * 24 * 90)
                movie_overview = movie.overview

                for genre in movie.genres:
                    if genres_list is None:
                        genres_list = "{}".format(genre.name)
                    else:
                        genres_list += "|{}".format(genre.name)
                movie_genres = genres_list
                r.set('movies.{}.title'.format(title.replace(" ", "_")
                                               ), movie.title)
                r.expire('movies.{}.title'.format(title.replace(" ", "_")
                                                  ), 60 * 60 * 24 * 90)
                r.set('movies.{}.runtime'.format(title.replace(" ", "_")
                                                 ), movie.runtime)
                r.expire('movies.{}.runtime'.format(title.replace(" ", "_")
                                                    ), 60 * 60 * 24 * 90)
                r.set('movies.{}.overview'.format(title.replace(" ", "_")
                                                  ), movie.overview)
                r.expire('movies.{}.overview'.format(title.replace(" ", "_")
                                                     ), 60 * 60 * 24 * 90)
                if movie_genres is not None:
                    r.set('movies.{}.genres'.format(title.replace(" ", "_")
                                                    ), movie_genres)
                    r.expire('movies.{}.genres'.format(title.replace(" ", "_")
                                                       ), 60 * 60 * 24 * 90)
            elif len(matches) > 1:
                r.set('movies.{}.title'.format(title.replace(" ", "_")
                                               ), "Multiples")
                r.expire('movies.{}.title'.format(title.replace(" ", "_")
                                                  ), 60 * 60 * 24 * 90)
                return
            else:
                r.set('movies.{}.title'.format(title.replace(" ", "_")
                                               ), "NotFound")
                r.expire('movies.{}.title'.format(title.replace(" ", "_")
                                                  ), 60 * 60 * 24 * 90)
                return

        if movie_title is None:
            log.debug('Movies: Ignored due to being not found before "%s"',
                      title)
            return

        if movie_posterurl:
            exists = False
            title_clean = re.sub(r'[^a-zA-Z0-9_.\s]+', '', title.strip())
            if not os.path.exists(os.path.join(output_folder, "Artwork",
                                  "Movies", title_clean)):
                os.makedirs(os.path.join(output_folder, "Artwork", "Movies",
                            title_clean))
            if os.path.exists(os.path.join(output_folder, "Artwork", "Movies",
                              title_clean, "poster.jpg")):
                exists = True

            if not exists:
                log.info('Movies: Adding poster to download list for %s', title)
                createNewDownloadThread(movie_posterurl,
                                        os.path.join(output_folder, "Artwork",
                                                     "Movies", title_clean,
                                                     "poster.jpg"))

            log.info('Movies: Adding poster location for %s', title)
            poster = ElementTree.SubElement(programme, 'icon')
            poster.set('src', str(os.path.join(output_folder, "Artwork",
                                               "Movies", title_clean,
                                               "poster.jpg")))

        if movie_genres:
            for c in movie_genres.split("|"):
                exists = False
                if not programme.findall('category') == []:
                    for old_cat in programme.findall('category'):
                        if old_cat.text == c:
                            exists = True
                        if not exists:
                            log.info('Movies: Adding category "%s"', c)
                            category = ElementTree.SubElement(programme, 'category')
                            category.text = c
                else:
                    log.info('Movies: Adding category "%s"', c)
                    category = ElementTree.SubElement(programme, 'category')
                    category.set('lang', 'en')
                    category.text = c

        log.info('Movies: Adding info from TMDB for %s', title)
        exists = False
        for old_cat in programme.findall('category'):
            if old_cat.text == 'movie':
                exists = True
        if not exists:
            log.info('Movies: Adding category "%s"', 'Movie')
            category = ElementTree.SubElement(programme, 'category')
            category.set('lang', 'en')
            category.text = 'movie'

        if movie_overview:
            log.info('Movies: Adding overview "%s"', movie_overview)
            if programme.find('desc') is not None:
                programme.find('desc').text = movie_overview
            else:
                desc = ElementTree.SubElement(programme, 'desc')
                desc.text = movie.overview

        if movie_runtime:
            log.info('Movies: Adding runtime "%s"', movie_runtime)
            if programme.find('length') is not None:
                programme.remove(programme.find('length'))
            length = ElementTree.SubElement(programme, 'length')
            length.set('units', 'minutes')
            length.text = str(movie_runtime)


class Series(BaseProcessor):
    """
        Augment TV shows  with data from thetvdb.com
        """

    def __init__(self):
        if not tmdbcheck:
            self.valid = False
            log.warning('Series: TMDB module not found.')
            return

        if TMDB_API is None:
            self.valid = False
            log.critical("TMDB API key missing")
            sys.exit(1)

        log.debug("Using TMDB API key %s", TMDB_API)
        tmdb = tmdbv3api.TMDb()
        tmdb.api_key = TMDB_API
        tmdb.language = 'en'

    def __call__(self, programme):
        if not self.valid:
            return

        # try:
        start = programme.get('start')
        stop = programme.get('stop')
        title = programme.find('title').text
        # channel = programme.get('channel')
        # episodes = programme.findall('episode-num')
        # except:
        #    log.debug('Series: Ignoring invalid programme')
        #    return
        if title is None:
            return
        if stop is None:
            return
        # Unfortunately strptime can't handle numeric timezones so we strip it.
        # It's only for getting possible movies so won't matter too much.
        if ' ' in start:
            start = start.split(' ')[0]
        if ' ' in stop:
            stop = stop.split(' ')[0]
        start_time = time.mktime(time.strptime(start, TIME_FORMAT))
        stop_time = time.mktime(time.strptime(stop, TIME_FORMAT))
        duration = stop_time - start_time

        if duration > 5400:
            log.debug('Series: Skipping "%s" since runtime over 90 minutes',
                      title)
            return

        series_poster = None
        if r.get('series.{}.title'.format(title.replace(" ", "_"))):
            if r.get('series.{}.title'.format(title.replace(" ", "_"))
                     ) == "NotFound":
                log.debug('Series: Series ignore for "%s"', title)
                return
            else:
                log.debug('Series: Cache hit for "%s"', title)
                if r.get('series.{}.poster'.format(title.replace(" ", "_"))
                         ) is not None:
                    series_poster = r.get('series.{}.poster'
                                          .format(title.replace(" ", "_"))
                                          ).decode('utf-8')
                    log.info('Series: Adding info from cache for %s', title)
                else:
                    log.debug('Series: Series ignored no poster for "%s"',
                              title)
                    return
        else:
            try:
                tvtmdb = tmdbv3api.TV()
                results = tvtmdb.search(title.replace('?', ''))
                log.debug('Series: Searching for title %s', title.replace('?', ''))
            except tmdbv3api.tmdb.TMDbException:
                log.exception('Series: TMDB problem searching')
                return
            matches = []
            for result in results:
                if result is not None:
                    if normalise_title(title) == normalise_title(result.name):
                        matches.append(result)
            log.debug('Series: Exact title matches: %d', len(matches))
            for series in matches:
                log.debug('Series: Found match "%s"', series.name)
            if len(matches) >= 1:
                try:
                    log.debug('Series: Cache miss for "%s"', title)
                    seriesdetails = matches[0]
                except tmdbv3api.tmdb.TMDbException:
                    log.exception('Series: TMDB problem fetching info')
                    return
                log.debug('Series: Cache miss for "%s"', title)
                tmdbconfiguration = tmdbv3api.Configuration()
                base_url = tmdbconfiguration.info().images['base_url']
                if seriesdetails.poster_path is not None:
                    series_poster = base_url + "w342" + seriesdetails.poster_path
                if series_poster is not None:
                    r.set('series.{}.title'.format(title.replace(" ", "_")),
                          title)
                    r.expire('series.{}.title'.format(title.replace(" ", "_")
                                                      ), 60 * 60 * 24 * 90)
                    series_poster = series_poster
                    r.set('series.{}.poster'.format(title.replace(" ", "_")
                                                    ), series_poster)
                    r.expire('series.{}.poster'.format(title.replace(" ", "_")
                                                       ), 60 * 60 * 24 * 90)
                    log.info('Series: Adding info from TVDB for %s', title)
                else:
                    log.debug('Series: No poster found "%s"', title)
                    r.set('series.{}.title'.format(title.replace(" ", "_")
                                                   ), "NotFound")
                    r.expire('series.{}.title'.format(title.replace(" ", "_")
                                                      ), 60 * 60 * 24 * 90)
                    return

        exists = False
        # Store the icon for the episode if there is one
        if series_poster is not None:
            exists = False
            title_clean = re.sub(r'[^a-zA-Z0-9_.\s]+', '', title.strip())
            if not os.path.exists(os.path.join(output_folder, "Artwork", "Series", title_clean)):
                os.makedirs(os.path.join(output_folder, "Artwork", "Series", title_clean))
            if os.path.exists(os.path.join(output_folder, "Artwork", "Series", title_clean, "poster.jpg")):
                exists = True
            if not exists:
                log.info('Series:Adding poster to download list for show "%s"',
                         title_clean)
                createNewDownloadThread(series_poster,
                                        os.path.join(output_folder, "Artwork", "Series", title_clean, "poster.jpg"))

            log.info('Series: Adding poster location for show "%s"', title_clean)
            poster = ElementTree.SubElement(programme, 'icon')
            poster.set('src', str(os.path.join(output_folder, "Artwork", "Series", title_clean, "poster.jpg")))


class Episodes(BaseProcessor):
    """
    Augment TV shows  with data from thetvdb.com
    """

    def __init__(self):
        self.cache = {}
        if not tmdbcheck:
            self.valid = False
            log.warning('Series: TMDB module not found.')
            return

        if TMDB_API is None:
            self.valid = False
            log.critical("TMDB API key missing")
            sys.exit(1)

        log.debug("Using TMDB API key %s", TMDB_API)
        tmdb = tmdbv3api.TMDb()
        tmdb.api_key = TMDB_API
        tmdb.language = 'en'

    def __call__(self, programme):
        if not self.valid:
            return

        try:
            start = programme.get('start')
            stop = programme.get('stop')
            title = programme.find('title').text
            episodes = programme.findall('episode-num')
        except tmdbv3api.tmdb.TMDbException:
            log.debug('Episodes: Ignoring invalid programme')
            return
        if stop is None:
            return
        # Unfortunately strptime can't handle numeric timezones so we strip it.
        # It's only for getting possible tv shows so won't matter too much.
        if ' ' in start:
            start = start.split(' ')[0]
        if ' ' in stop:
            stop = stop.split(' ')[0]
        start_time = time.mktime(time.strptime(start, TIME_FORMAT))
        stop_time = time.mktime(time.strptime(stop, TIME_FORMAT))
        duration = stop_time - start_time
        if duration > 5400:  # give up if longer than 90 minutes
            return

        try:
            for episode in episodes:
                # TODO: is TVDB data really useless without episode numbers?
                # There's a good chance we can find some details without...
                if episode.get('system') == "xmltv_ns":
                    # log.debug('Episodes: episode "%s"', episode.text)
                    season = int(episode.text.split('.')[0]) + 1
                    episode = int(episode.text.split('.')[1]) + 1

                    log.debug('Episodes: Looking up season %s, episode %s '
                              ' of show "%s" at TVDB', season, episode, title)
                    # get data from TMDB
                    try:
                        tvtmdb = tmdbv3api.TV()
                        results = tvtmdb.search(title.replace('?', ''))
                    except tmdbv3api.tmdb.TMDbException:
                        log.exception('Episodes: TMDB problem searching')
                        return
                    matches = []
                    for result in results:
                        if result is not None:
                            if normalise_title(title) == normalise_title(result.name):
                                matches.append(result)
                    log.debug('Series: Exact title matches: %d', len(matches))
                    for series in matches:
                        log.debug('Series: Found match "%s" (%s)', series.name)
                    if len(matches) >= 1:
                        try:
                            log.debug('Series: Cache miss for "%s"', title)
                            series_title = matches[0].id
                        except tmdbv3api.tmdb.TMDbException:
                            log.exception('Series: TMDB problem fetching info')
                            return
                        tvtmdb = tmdbv3api.TV()
                        episodetmdb = tmdbv3api.Episode()
                        series = tvtmdb.search(title.replace('?', ''))
                        episodedetails = episodetmdb.details(matches[0], season, episode)
                        episodename = episodedetails.name
                        rating = episodedetails.vote_average
                        genres = series_title.genres
                        tmdbconfiguration = tmdbv3api.Configuration()
                        base_url = tmdbconfiguration.info().images['base_url']
                        series_poster = base_url + "w342" + matches[0].poster_path
                        # TODO: add first aired date.
                        # log.debug('Episodes: TVDB items are "%s"', list(tvdb_episode[title][season][episode].items()))

                        # store the subtitle/episode name
                        subtitle = ElementTree.SubElement(programme, 'sub-title')
                        subtitle.text = episodename
                        log.info('Episodes: Subtitle for "%s" is "%s"', title, episodename)

                        # store the rating
                        if rating is not None:
                            log.info('Episodes: Adding rating "%s"', rating)
                            if programme.find('star-rating') is not None:
                                programme.remove(programme.find('star-rating'))
                            urating = ElementTree.SubElement(programme, 'star-rating')
                            value = ElementTree.SubElement(urating, 'value')
                            value.text = str('%s/10' % rating)

                        # store the genres
                        log.debug('Episodes: genres "%s"', genres)
                        if genres:
                            # if 'categories' in movie and 'genre' in movie['categories']:
                            for c in genres:
                                if c:
                                    exists = False
                                    for old_cat in programme.findall('category'):
                                        if old_cat.text == c:
                                            exists = True
                                    if not exists:
                                        log.info('Episodes: Adding category "%s"', c)
                                        category = ElementTree.SubElement(programme, 'category')
                                        category.text = c

                        exists = False
                        if series_poster is not None:
                            exists = False
                            title_clean = re.sub(r'[^a-zA-Z0-9_.\s]+', '', title.strip())
                            if not os.path.exists(os.path.join(output_folder, "Artwork", "Series", title_clean)):
                                os.makedirs(os.path.join(output_folder, "Artwork", "Series", title_clean))
                            if os.path.exists(os.path.join(output_folder, "Artwork", "Series", title_clean, "poster.jpg")):
                                exists = True
                            if not exists:
                                log.info('Series:Adding poster to download list for show "%s"', title_clean)
                                createNewDownloadThread(series_poster, os.path.join(output_folder, "Artwork", "Series", title_clean, "poster.jpg"))

                            log.info('Series: Adding poster location for show "%s"', title_clean)
                            poster = ElementTree.SubElement(programme, 'icon')
                            poster.set('src', str(os.path.join(output_folder, "Artwork", "Series", title_clean, "poster.jpg")))

        except:
            log.exception('Episodes: TVDB problem searching')
            return


class HD(BaseProcessor):
    """
    Look for a HD note in a description.
    """
    regexes = (
        re.compile(r'HD\.?$'),
        re.compile(r'\(HD\)$'),
    )

    def __call__(self, programme):
        desc = programme.find('desc')
        if desc is not None and desc.text:
            for regex in self.regexes:
                matched = regex.search(desc.text)
                if matched:
                    log.debug('HD: Found "%s"', programme.find('title').text)
                    if programme.find('video') is not None:
                        if programme.find('quality') is None:
                            quality = ElementTree.SubElement(programme.find('video'), 'quality')
                            quality.text = 'HDTV'
                        elif programme.find('quality').text != 'HDTV':
                            programme.find('quality').text = 'HDTV'
                    else:
                        video = ElementTree.SubElement(programme, 'video')
                        present = ElementTree.SubElement(video, 'present')
                        present.text = 'yes'
                        aspect = ElementTree.SubElement(video, 'aspect')
                        aspect.text = '16:9'
                        quality = ElementTree.SubElement(video, 'quality')
                        quality.text = 'HDTV'
                    desc.text = regex.sub('', desc.text)


class Subtitle(BaseProcessor):
    """
    Look for a subtitle in a description.
    """
    regexes = (
        re.compile(r"(Today|Tonight)?:? ?'(?P<subtitle>.*?)'\.\s?"),
        re.compile(r"'(?P<subtitle>.{2,60}?)\.'\s"),
        re.compile(r"(?P<subtitle>.{2,60}?):\s"),
    )

    def __call__(self, programme):
        desc = programme.find('desc')
        if desc is not None and desc.text:
            for regex in self.regexes:
                matched = regex.match(desc.text)
                if matched and 'subtitle' not in programme:
                    subtitle = ElementTree.SubElement(programme, 'sub-title')
                    subtitle.text = matched.group('subtitle')
                    log.debug('Subtitle: "%s" for "%s"', subtitle.text, programme.find('title').text)
                    desc.text = regex.sub('', desc.text)


class EpDesc(BaseProcessor):
    """
    Look for a Season/Episode info in a description.
    """
    desc_regexes = (
        re.compile(r' S\s?(\d+) Ep\s?(\d+)'),
    )
    progid_regexes = (
        re.compile(r'\s?(\d+)Ep\s?(\d+)'),
    )

    def __call__(self, programme):
        desc = programme.find('desc')
        if desc is not None and desc.text:
            for regex in self.desc_regexes:
                matched = regex.search(desc.text)
                if matched:
                    season, episode = [int(x) for x in matched.groups()]
                    log.debug('EpDesc: From desc: Found season %s episode %s for "%s"', season, episode, programme.find('title').text)
                    episode_num = ElementTree.SubElement(programme, 'episode-num')
                    episode_num.set('system', 'xmltv_ns')
                    episode_num.text = '%s.%s.0' % (season - 1, episode - 1)
        # choice tv puts the season number in the guide data. lets get it!
        # TODO: they use the same format for movies. shouldn't insert those.
        episodes = programme.findall('episode-num')
        for episode in episodes:
            if episode.get('system') == "dd_progid":
                for regex in self.progid_regexes:
                    matched = regex.search(episode.text)
                    if matched:
                        season, ep = [int(x) for x in matched.groups()]
                        log.debug('EpDesc: episode "%s"', episode.text)
                        log.debug('EpDesc: From dd_progid: Found season %s episode %s for "%s"', season, ep, programme.find('title').text)
                        episode_num = ElementTree.SubElement(programme, 'episode-num')
                        episode_num.set('system', 'xmltv_ns')
                        episode_num.text = '%s.%s.0' % (season - 1, ep - 1)


def compare_programme(x):
    """
       Comparison helper to sort the children elements of an
       XMLTV programme tag.
    """
    programme_order = (
        'title', 'sub-title', 'desc', 'credits', 'date',
        'category', 'language', 'orig-language', 'length',
        'icon', 'url', 'country', 'episode-num', 'video', 'audio',
        'previously-shown', 'premiere', 'last-chance', 'new',
        'subtitles', 'rating', 'star-rating',
    )
    # TODO: don't know if the fillowing line errors when not found or returns 0
    return programme_order.index(x.tag)


def normalise_title(title):
    """
    Normalise titles to help comparisons.
    """
    normalised = title.lower()
    if normalised.startswith('the '):
        normalised = normalised[4:]
    normalised = re.sub('[^a-z ]', '', normalised)
    normalised = re.sub(' +', ' ', normalised)
    normalised = normalised.replace(' the ', ' ')
    return normalised


def indent(elem, level=0):
    """
    Make ElementTree output pretty.
    """
    i = "\n" + level * "\t"
    if len(elem):
        if not elem.text or not elem.text.strip():
            elem.text = i + "\t"
        if not elem.tail or not elem.tail.strip():
            elem.tail = i
        for elem in elem:
            indent(elem, level + 1)
        if not elem.tail or not elem.tail.strip():
            elem.tail = i
    else:
        if level and (not elem.tail or not elem.tail.strip()):
            elem.tail = i


def download(link, filelocation):
    if not os.path.exists(os.path.dirname(filelocation.strip())):
        log.info('Made Directory: "%s"', os.path.dirname(filelocation.strip()))
        os.makedirs(os.path.dirname(filelocation.strip()))
    r = requests.get(link.replace("http://thetvdb", "http://www.thetvdb"), stream=True)
    with open(filelocation, 'wb') as f:
        for chunk in r.iter_content(1024):
            if chunk:
                f.write(chunk)


def createNewDownloadThread(link, filelocation):
    threads = []
    t = threading.Thread(target=download, args=(link, filelocation))
    threads.append(t)
    t.start()
    # cap the threads if over limit
    while threading.active_count() >= threadcount:
        threads = threading.active_count()
        time.sleep(5)


#############################################################################
# ---------------------------------------------------------------------------
# Main loop
# ---------------------------------------------------------------------------
#############################################################################
if __name__ == '__main__':

    output_folder = "/output"
    output_folder = os.path.join(str(Path.home()), output_folder)
    log.info("Output Folder %s", output_folder)

    parser = OptionParser(version='%prog ' + str(VERSION))
    parser.set_defaults(debug=False)
    parser.add_option('-d', '--debug', action='store_true',
                      help='output debugging information.')
    parser.add_option('-v', '--verbose', action='store_true',
                      help='output verbose information.')
    parser.add_option('-o', '--output', action='store', metavar='FILE',
                      help='set output directory for artwork instead of "' + output_folder + '".')
    (options, args) = parser.parse_args()

    if options.verbose:
        log.setLevel(logging.INFO)

    if options.debug:
        log.setLevel(logging.DEBUG)

    if options.output:
        output_folder = options.output
        log.info('Using output folder "%s" ', options.output)

    # What are we working with?
    if sys.stdin.isatty():
        if len(args) == 0:
            log.critical('No input file to process.')
            sys.exit(2)
        try:
            data = open(args[0]).read()
        except IOError:
            log.critical('Could not open input file "%s"', args[0])
            sys.exit(2)
    else:
        data = sys.stdin.read()

    processors = [
        Subtitle(),                 # extract the show sub-title from the title, which is often where
        # EpDesc(),                  # find season/episode in the description
        HD(),                       # check the description for clues the show in in HD and flag accordingly
        Movies(),                   # augment the guide data with info from TMDB
        Series(),
        Episodes(),                 # augment the guide data with info from TVDB
    ]

    tree = ElementTree.XML(data)
    for processor in processors:
        for programme in tree.findall('.//programme'):
            try:
                processor(programme)
            except:
                log.exception("Failed processing with processor: %s", processor)
    try:
        processor.post_process(tree)
    except NotImplementedError:
        pass
    except:
        log.exception("Failed post processing with processor: %s", processor)

    for programme in tree.findall('.//programme'):
        programme[:] = sorted(programme, key=compare_programme)

    indent(tree)

    f = open(os.path.join(output_folder, "enhanced-xmltv.xml"), "w")
    print('<?xml version="1.0" encoding="utf-8"?>', file=f)
    print((ElementTree.tostring(tree, encoding='unicode', method='xml')), file=f)
    f.close()

    # monitor for threads winding down
    while threading.active_count() != 1:
        threads = threading.active_count()
        string = "Active download threads running - " + str(threads)
        logging.debug(string)
        time.sleep(5)
