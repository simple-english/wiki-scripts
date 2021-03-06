#! /usr/bin/env python3

import logging

from . import CacheDb, CacheDbError
from .. import utils

logger = logging.getLogger(__name__)

__all__ = ["AllRevisionsProps"]

# TODO:
# The categorization of a revision as normal/deleted will inevitably get out of date,
# but most of the properties of each revision are still valid. Deleted revisions don't
# have the "parentid" attribute and deleted pages have "pageid == 0". It would be
# possible to just read the deletion log, but the question is what happens to pageid
# when a page is deleted/restored.
# If the association between pageid and revids is needed in the future, don't forget
# to also check the merge log.

class AllRevisionsProps(CacheDb):
    def __init__(self, api, cache_dir, autocommit=True):
        # check for necessary rights
        if "deletedhistory" in api.user.rights:
            self.deletedrevisions = True
        else:
            logger.warning("The current user does not have the 'deletedhistory' right. Properties of deleted revisions will not be available.")
            self.deletedrevisions = False

        super().__init__(api, cache_dir, "AllRevisionsProps", autocommit)

    def init(self, key=None):
        """
        :param key: ignored
        """
        self.data = {}
        self.data["badrevids"] = []
        self.data["revisions"] = []
        self.data["deletedrevisions"] = []
        self.update()

    def update(self, key=None):
        """
        :param key: ignored
        """
        # TODO: remove this at some point
        if "deletedrevisions" not in self.data:
            raise CacheDbError("The \"deletedrevisions\" key is not present. Please reinitialize the AllRevisionsProps cache.")

        # get revision IDs of first and last revision to fetch
        firstrevid = self._get_last_revid_db() + 1
        lastrevid = self.api.last_revision_id

        if lastrevid >= firstrevid:
            self._fetch_revisions(firstrevid, lastrevid)

            self._update_timestamp()

            if self.autocommit is True:
                self.dump()

    def _get_last_revid_db(self):
        """
        Get ID of the last revision stored in the cache database.
        """
        try:
            return self.data["revisions"][-1]["revid"]
        except IndexError:
            # empty database
            return 0

    def _fetch_revisions(self, first, last):
        """
        Fetch properties of revisions in given numeric range and save the data
        to the database.

        :param first: (int) revision ID to start fetching from
        :param last: (int) revision ID to end fetching
        """
        # not necessary to wrap in each iteration since lists are mutable
        wrapped_revids = utils.ListOfDictsAttrWrapper(self.data["revisions"], "revid")
        wrapped_deletedrevids = utils.ListOfDictsAttrWrapper(self.data["deletedrevisions"], "revid")

        for chunk in utils.list_chunks(range(first, last + 1), self.api.max_ids_per_query):
            logger.info("Fetching revids %s-%s" % (chunk[0], chunk[-1]))
            revids = "|".join(str(x) for x in chunk)
            if self.deletedrevisions is True:
                result = next(self.api.query_continue(action="query", revids=revids, prop="revisions|deletedrevisions", drvlimit="max"))
            else:
                result = self.api.call_api(action="query", revids=revids, prop="revisions")

            # TODO: what is the meaning of badrevids?
            badrevids = result.get("badrevids", {})
            for _, badrev in badrevids.items():
                utils.bisect_insert_or_replace(self.data["badrevids"], badrev["revid"])

            pages = result.get("pages", {})
            for _, page in pages.items():
                # handle normal revisions
                revisions = page.get("revisions", [])
                for r in revisions:
                    utils.bisect_insert_or_replace(self.data["revisions"], r["revid"], data_element=r, index_list=wrapped_revids)

                # handle deleted revisions
                deletedrevisions = page.get("deletedrevisions", [])
                for r in deletedrevisions:
                    utils.bisect_insert_or_replace(self.data["deletedrevisions"], r["revid"], data_element=r, index_list=wrapped_deletedrevids)
