#! /usr/bin/env python3

# FIXME:
#   handle :Category and Category links properly
#   how hard is skipping code blocks?

# TODO:
#   extlink -> wikilink conversion should be done first
#   skip category links, article status templates
#   detect self-redirects (definitely interactive only)

import re
import logging

import mwparserfromhell

from ws.core import API, APIError
from ws.interactive import *
import ws.ArchWiki.lang as lang
from ws.parser_helpers.title import canonicalize, Title

logger = logging.getLogger(__name__)

class LinkChecker:
    """
    Assumptions:

    - all titles are case-insensitive on the first letter (true on ArchWiki)
    - alternative text is intentional, no replacements there
    """
    def __init__(self, api, interactive=False):
        self.api = api
        self.interactive = interactive

        # TODO: when there are many different changes, create a page on ArchWiki
        # describing the changes, link it with wikilink syntax using a generic
        # alternative text (e.g. "semi-automatic style fixes") (path should be
        # configurable, as well as the URL fallback)
        if interactive is True:
            self.edit_summary = "simplification of wikilinks, fixing whitespace and capitalization, removing underscores (https://github.com/lahwaacz/wiki-scripts/blob/master/link-checker.py (interactive))"
        else:
            self.edit_summary = "simplification of wikilinks, fixing whitespace (https://github.com/lahwaacz/wiki-scripts/blob/master/link-checker.py)"

        # redirects only to the Main, ArchWiki and Help namespaces, others deserve special treatment
        self.redirects = api.redirects_map(target_namespaces=[0, 4, 12])

        # mapping of canonical titles to displaytitles
        self.displaytitles = {}
        for ns in self.api.namespaces.keys():
            if ns < 0:
                continue
            for page in self.api.generator(generator="allpages", gaplimit="max", gapnamespace=ns, prop="info", inprop="displaytitle"):
                self.displaytitles[page["title"]] = page["displaytitle"]

    def check_trivial(self, wikilink):
        """
        Perform trivial simplification, replace `[[Foo|foo]]` with `[[foo]]`.

        :param wikilink: instance of `mwparserfromhell.nodes.wikilink.Wikilink`
                         representing the link to be checked
        """
        # Wikicode.matches() ignores even the '#' character indicating relative links;
        # hence [[#foo|foo]] would be replaced with [[foo]]
        # Our canonicalize() function does exactly what we want and need.
        if wikilink.text is not None and canonicalize(wikilink.title) == canonicalize(wikilink.text):
            # title is mandatory, so the text becomes the title
            wikilink.title = wikilink.text
            wikilink.text = None

    def check_relative(self, wikilink, title, srcpage):
        """
        Use relative links whenever possible. For example, links to sections such as
        `[[Foo#Bar]]` on a page `title` are replaced with `[[#Bar]]` whenever `Foo`
        redirects to or is equivalent to `title`.

        :param wikilink: the link to be checked
        :type wikilink: :py:class:`mwparserfromhell.nodes.wikilink.Wikilink`
        :param title: the parsed :py:attr:`wikilink.title`
        :type title: :py:class:`mw.parser_helpers.title.Title`
        :param str srcpage: the title of the page being checked
        """
        if title.iwprefix or not title.sectionname:
            return
        # check if title is a redirect
        target = self.redirects.get(title.fullpagename)
        if target:
            _title = Title(self.api, target)
            _title.sectionname = title.sectionname
        else:
            _title = title

        if canonicalize(srcpage) == _title.fullpagename:
            wikilink.title = "#" + _title.sectionname
            title.parse(wikilink.title)

    def check_redirect_exact(self, wikilink, title):
        """
        Replace `[[foo|bar]]` with `[[bar]]` if `foo` and `bar` point to the
        same page after resolving redirects.

        :param wikilink: the link to be checked
        :type wikilink: :py:class:`mwparserfromhell.nodes.wikilink.Wikilink`
        :param title: the parsed :py:attr:`wikilink.title`
        :type title: :py:class:`mw.parser_helpers.title.Title`
        """
        if wikilink.text is None:
            return

        text = Title(self.api, wikilink.text)

        # skip anything with section anchors, which would be lost otherwise
        if title.sectionname or text.sectionname:
            return

        target1 = self.redirects.get(title.fullpagename)
        target2 = self.redirects.get(text.fullpagename)
        if target1 is not None and target2 is not None:
            if target1 == target2:
                wikilink.title = wikilink.text
                wikilink.text = None
                title.parse(wikilink.title)
        elif target1 is not None:
            if target1 == text.fullpagename:
                wikilink.title = wikilink.text
                wikilink.text = None
                title.parse(wikilink.title)
        elif target2 is not None:
            if target2 == title.fullpagename:
                wikilink.title = wikilink.text
                wikilink.text = None
                title.parse(wikilink.title)

    def check_redirect_capitalization(self, wikilink, title):
        """
        Avoid redirect iff the difference is only in capitalization.

        :param wikilink: the link to be checked
        :type wikilink: :py:class:`mwparserfromhell.nodes.wikilink.Wikilink`
        :param title: the parsed :py:attr:`wikilink.title`
        :type title: :py:class:`mw.parser_helpers.title.Title`
        """
        # run only in interactive mode
        if self.interactive is False:
            return

        # FIXME: very common false positive
        if title.pagename == "Wpa supplicant":
            return

        # might be only a section, e.g. [[#foo]]
        if title.fullpagename:
            target = self.redirects.get(title.fullpagename)
            if target is not None and target.lower() == title.fullpagename.lower():
                wikilink.title = target
                if title.sectionname:
                    # TODO: check how canonicalization of section anchor works; previously we only replaced underscores
                    # (this is run only in interactive mode anyway)
                    wikilink.title = str(wikilink.title) + "#" + title.sectionname
                title.parse(wikilink.title)

    def check_displaytitle(self, wikilink, title):
        # Replacing underscores and capitalization as per DISPLAYTITLE attribute
        # is not safe (e.g. 'wpa_supplicant' and 'WPA supplicant' are equivalent
        # without deeper context), so do it only in interactive mode.
        if self.interactive is False:
            return
        # Avoid largescale edits if there is an alternative text.
        if wikilink.text is not None:
            return
        # we can't check interwiki links
        if title.iwprefix:
            return
        # skip relative links
        if not title.fullpagename:
            return
        # report pages without DISPLAYTITLE (red links)
        if title.fullpagename not in self.displaytitles:
            logger.warning("wikilink to non-existing page: {}".format(wikilink))
            return

        # FIXME: avoid stripping ":" in the [[:Category:...]] links
        if title.namespace == "Category":
            return

        # FIXME: very common false positive
        if title.pagename == "Wpa supplicant":
            return

        # assemble new title
        new = self.displaytitles[title.fullpagename]
        if title.sectionname:
            # NOTE: section anchor should be checked in self.check_anchor(), so
            #       canonicalization here does not matter
            new += "#" + title.sectionname

        # skip first-letter case differences
        if wikilink.title[1:] != new[1:]:
            wikilink.title = new
            title.parse(wikilink.title)

    def check_anchor(self, wikilink, title):
        # TODO: look at the actual section heading (beware of https://phabricator.wikimedia.org/T20431)
        #   - try exact match first
        #   - otherwise try case-insensitive match to detect differences in capitalization
        #   - otherwise report (or just mark with {{Broken fragment}} ?)
        #   - someday maybe: check N older revisions, section might have been renamed (must be interactive!) or moved to other page (just report)
        pass

    def collapse_whitespace_pipe(self, wikilink):
        """
        Strip whitespace around the pipe in wikilinks.

        :param wikilink: instance of `mwparserfromhell.nodes.wikilink.Wikilink`
                         representing the link to be checked
        """
        if wikilink.text is not None:
            wikilink.title = wikilink.title.rstrip()
            wikilink.text = wikilink.text.lstrip()

    def collapse_whitespace(self, wikicode, wikilink):
        """
        Attempt to fix spacing around wiki links after the substitutions.

        :param wikicode: instance of `mwparserfromhell.wikicode.Wikicode`
                         containing the wikilink
        :param wikilink: instance of `mwparserfromhell.nodes.wikilink.Wikilink`
                         representing the link to be checked
        """
        parent, _ = wikicode._do_strong_search(wikilink, True)
        index = parent.index(wikilink)

        def _get_text(index):
            try:
                node = parent.get(index)
                if not isinstance(node, mwparserfromhell.nodes.text.Text):
                    return None
                return node
            except IndexError:
                return None

        prev = _get_text(index - 1)
        next_ = _get_text(index)

        if prev is not None and (prev.endswith(" ") or prev.endswith("\n")):
            wikilink.title = wikilink.title.lstrip()
        if next_ is not None and (next_.startswith(" ") or next_.endswith("\n")):
            if wikilink.text is not None:
                wikilink.text = wikilink.text.rstrip()
            else:
                wikilink.title = wikilink.title.rstrip()

    def update_page(self, title, text):
        """
        Parse the content of the page and call various methods to update the links.

        :param title: title of the page (as `str`)
        :param text: content of the page (as `str`)
        :returns: updated content (as `str`)
        """
        logger.info("Parsing '%s'..." % title)
        wikicode = mwparserfromhell.parse(text)

        for wikilink in wikicode.ifilter_wikilinks(recursive=True):
            wl_title = Title(self.api, wikilink.title)
            # skip interlanguage links (handled by update-interlanguage-links.py)
            if wl_title.iw in self.api.interlanguagemap.keys():
                continue

            self.collapse_whitespace_pipe(wikilink)
            self.check_trivial(wikilink)
            self.check_relative(wikilink, wl_title, title)
            self.check_redirect_exact(wikilink, wl_title)
            self.check_redirect_capitalization(wikilink, wl_title)
            self.check_displaytitle(wikilink, wl_title)

            # collapse whitespace around the link, e.g. 'foo [[ bar]]' -> 'foo [[bar]]'
            self.collapse_whitespace(wikicode, wikilink)

        return str(wikicode)

    def process_page(self, title):
        result = self.api.call_api(action="query", prop="revisions", rvprop="content|timestamp", titles=title)
        page = list(result["pages"].values())[0]
        timestamp = page["revisions"][0]["timestamp"]
        text_old = page["revisions"][0]["*"]
        text_new = self.update_page(title, text_old)
        self._edit(title, page["pageid"], text_new, text_old, timestamp)

    def process_allpages(self, apfrom=None):
        for page in self.api.generator(generator="allpages", gaplimit="100", gapfilterredir="nonredirects", gapfrom=apfrom, prop="revisions", rvprop="content|timestamp"):
            title = page["title"]
            if lang.detect_language(title)[1] != "English":
                continue
            timestamp = page["revisions"][0]["timestamp"]
            text_old = page["revisions"][0]["*"]
            text_new = self.update_page(title, text_old)
            self._edit(title, page["pageid"], text_new, text_old, timestamp)

    def _edit(self, title, pageid, text_new, text_old, timestamp):
        if text_old != text_new:
            try:
                if self.interactive is False:
                    self.api.edit(title, pageid, text_new, timestamp, self.edit_summary, bot="")
                else:
                    edit_interactive(self.api, title, pageid, text_old, text_new, timestamp, self.edit_summary, bot="")
            except APIError as e:
                pass


if __name__ == "__main__":
    import ws.config
    import ws.logging

    argparser = ws.config.getArgParser(description="Parse all pages on the wiki and try to fix/simplify/beautify links")
    API.set_argparser(argparser)

    # TODO: move to LinkChecker.set_argparser()
    _script = argparser.add_argument_group(title="script parameters")
    _script.add_argument("-i", "--interactive", action="store_true",
            help="enables interactive mode")
    _mode = _script.add_mutually_exclusive_group()
    _mode.add_argument("--first", default=None, metavar="TITLE",
            help="the title of the first page to be processed")
    _mode.add_argument("--title",
            help="the title of the only page to be processed")

    args = argparser.parse_args()

    # set up logging
    ws.logging.init(args)

    api = API.from_argparser(args)

    # ensure that we are authenticated
    require_login(api)

    checker = LinkChecker(api, args.interactive)
    try:
        # TODO: simplify for the LinkChecker.from_argparser factory
        if args.title:
            checker.process_page(args.title)
        else:
            checker.process_allpages(apfrom=args.first)
    except InteractiveQuit:
        pass
