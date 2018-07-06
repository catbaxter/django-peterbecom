import re

from pipeline.finders import PipelineFinder

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured


class LeftoverPipelineFinder(PipelineFinder):
    """This finder is expected to come AFTER pipeline.finders.PipelineFinder
    in settings.STATICFILES_FINDERS.
    If a path is looked for here it means it's trying to find a file
    that pipeline.finders.PipelineFinder couldn't find.
    """

    def find(self, path, all=False):
        # If we're here, the file couldn't be found in any of the other
        # staticfiles finders. Before we raise an error, try to find out where,
        # in the bundles, this was defined. This will make it easier to correct
        # the mistake.
        # print("PATH", path)
        for config_name in "STYLESHEETS", "JAVASCRIPT":
            config = settings.PIPELINE[config_name]
            for key, directive in config.items():
                if path in directive["source_filenames"]:
                    raise ImproperlyConfigured(
                        "Static file {} can not be found anywhere. Defined in "
                        "PIPELINE[{!r}][{!r}]['source_filenames']".format(
                            path, config_name, key
                        )
                    )

        if settings.DEBUG and re.findall("\.[a-f0-9]{12}\.", path):
            # E.g. images/favicon-32.2f7785a88cef.png
            return
        # If the file can't be found AND it's not in bundles, there's
        # got to be something else really wrong.
        raise NotImplementedError(path)
