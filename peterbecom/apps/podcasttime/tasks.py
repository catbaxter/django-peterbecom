from celery.task import task

from peterbecom.apps.base.helpers import thumbnail
from peterbecom.apps.podcasttime.models import Podcast, PodcastError
from peterbecom.apps.podcasttime.scraper import (
    download_episodes,
    itunes_search,
)


@task()
def download_episodes_task(podcast_id, verbose=True):
    podcast = Podcast.objects.get(id=podcast_id)
    download_episodes(podcast, verbose=verbose)


@task()
def redownload_podcast_image(podcast_id):
    podcast = Podcast.objects.get(id=podcast_id)
    print "REDOWNLOAD_PODCAST_IMAGE!!"
    try:
        podcast.download_image()
        # If it worked, it should be possible to make a thumbnail out of
        # if. I've seen downloaded images with the right content-type,
        # and with a size but when you try to turn it into a thumbnail
        # PIL throws IOErrors.
        assert podcast.image
        thumbnail(podcast.image, '300x300')
        print "Worked!"
    except Exception:
        print "Failed!"
        PodcastError.create(podcast)
        raise


@task()
def fetch_itunes_lookup(podcast_id):
    podcast = Podcast.objects.get(id=podcast_id)
    results = itunes_search(podcast)
    if results['resultCount'] == 1:
        lookup = results['results'][0]
        podcast.itunes_lookup = lookup
        podcast.save()
