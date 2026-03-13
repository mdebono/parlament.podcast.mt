# Podcast Feed

from feedgenerator import Rss201rev2Feed
from feedgenerator import iri_to_uri

class PodcastFeed(Rss201rev2Feed):
    ns = "xmlns:itunes"
    ns_url = "http://www.itunes.com/dtds/podcast-1.0.dtd"

    def __init__(self, title, link, description, language=None, image_url=None, owner=None, author=None, category=None, **kwargs):
        super().__init__(title, link, description, language, None, None, None, None, None, None, None, None, None, None, **kwargs)
        self.feed['image_url'] = iri_to_uri(image_url)
        self.feed['owner'] = owner
        self.feed['author'] = author
        self.feed['category'] = category

    def rss_attributes(self):
        attributes = super().rss_attributes()
        attributes[self.ns] = self.ns_url
        return attributes

    def add_root_elements(self, handler):
        super().add_root_elements(handler)

        if self.feed['image_url'] is not None:
            handler.addQuickElement('itunes:image', '', {'href' : self.feed['image_url']})
        if self.feed['owner'] is not None:
            handler.startElement('itunes:owner', {})
            handler.addQuickElement('itunes:email', self.feed['owner'])
            handler.endElement('itunes:owner')
        if self.feed['author'] is not None:
            handler.addQuickElement('itunes:author', self.feed['author'])
        if self.feed['category'] is not None:
            handler.addQuickElement('itunes:category', '', {'text': self.feed['category']})
