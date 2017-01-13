from elasticsearch_dsl import (
    DocType,
    Float,
    Text,
    Integer,
    Date,
    Index,
    analyzer,
    Keyword,
    token_filter,
)

from django.conf import settings


edge_ngram_analyzer = analyzer(
    'edge_ngram_analyzer',
    type='custom',
    tokenizer='standard',
    filter=[
        'lowercase',
        token_filter(
            'edge_ngram_filter', type='edgeNGram',
            min_gram=1, max_gram=20
        )
    ]
)


class PodcastDoc(DocType):
    id = Keyword(required=True)
    thumbnail_348 = Keyword()
    thumbnail_160 = Keyword()
    times_picked = Integer()
    episodes_count = Integer()
    episodes_seconds = Float()
    slug = Keyword(required=True, index=False)
    # url = Keyword(required=True, index=False)
    name = Text(
        required=True,
        analyzer=edge_ngram_analyzer,
        search_analyzer='standard'
    )
    last_fetch = Date()
    latest_episode = Date()


# create an index and register the doc types
index = Index(settings.ES_INDEX)
index.settings(**settings.ES_INDEX_SETTINGS)
index.doc_type(PodcastDoc)
