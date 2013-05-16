#
#    Khan Academy Exercises for Course Builder
#
#    Copyright (C) 2013 Pavel Simakov (pavel@vokamis.com)
#    https://github.com/psimakov/khan-exercises-coursebuilder
#
#    This library is free software; you can redistribute it and/or
#    modify it under the terms of the GNU Lesser General Public
#    License as published by the Free Software Foundation; either
#    version 2.1 of the License, or (at your option) any later version.
#
#    This library is distributed in the hope that it will be useful,
#    but WITHOUT ANY WARRANTY; without even the implied warranty of
#    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU
#    Lesser General Public License for more details.
#
#    You should have received a copy of the GNU Lesser General Public
#    License along with this library; if not, write to the Free Software
#    Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston, MA  02110-1301,
#    USA
#

"""Khan Academy Exercises for Course Builder.


This extension lets you host Khan Academy exercises in your Course Builder
course. These exercises make learning complex subjects fun and they are free to
everyone! However, the framework is very complex; it's difficult to embed its
exercises into another web site. We made framework changes, which make it
easier to embed the exercises and collect the exercise results right in your
Course Builder course.

Here is how to install, activate and use this module:
    - download Course Builder (1.4.x)
    - download this package
    - copy all files in this package into /modules/khanex/... folder of your
      Course Builder application folder
    - edit main.app of your application
        - add new import where all other modules are imported:
          import modules.khanex.khanex
        - enable the module, where all other modules are enabled:
          modules.khanex.khanex.register_module().enable()
    - restart your local development sever or re-deployyour application
    - edit a lesson using visual editor; you should be able to add a new
      component type "Khan Academy Exercise"
    - the component editor should show a list of all exercises available in a
      dropdown list
    - pick one exercise, save the component configuration, save  the lesson
    - preview the lesson
    - click "Check Answer" and see how data is recorded in the datastore
      EventEntity table with a namespace appropriate for your course
    - this is it!

This work is based on my other project, which brings Khan Academy exercises to
WordPress. You can learn more about it here:
  http://www.softwaresecretweapons.com/jspwiki/khan-exercises

Here are the things I found difficult to do while completing this integration:
    - it is not possible to create a namespaced zip file handler; this is
      related to sub-optimal URL matching scheme used in sites.py; we only
      support only two path match expressions: 'starts-with /assets/...' or
      'is equal to /xyz'; for zip file serving on namespaced URL we need
      an expression 'starts with /xyz/...'
    - we do not have a function add_tag_definition(), which allows adding tag
      dynamically from inside the module; so I had to create an additional file
      inside /extenstions/... while I already had all my files in /modules/...
    - we do escape the content of <scrip>...</script> tag; thus it is impossible
      to have raw JavaScript in the tag; we need to make an exception for
      <script> to render its TEXT content unescaped

We need to improve these over time.

Good luck!
"""

__author__ = 'Pavel Simakov (pavel@vokamis.com)'

import cgi
import os
import urllib2
import urlparse
from xml.etree import cElementTree
import zipfile

import appengine_config
from common import schema_fields
from common import tags
from controllers import sites
from controllers import utils
from models import custom_modules
from models import models
from models import transforms

from google.appengine.api import namespace_manager


ZIP_FILE = os.path.join(os.path.dirname(__file__), 'khan-exercises.zip')
RELATIVE_URL_BASE = 'extensions/tags/khanex/resources'
URL_BASE = '/' + RELATIVE_URL_BASE
EXERCISE_BASE = 'khan-exercises/khan-exercises/exercises/'

EXERCISE_HTML_PAGE_RAW = (
    """<!DOCTYPE html>
<html">
<head>
    <meta http-equiv="Content-Type" content="text/html; charset=UTF-8">
<head>
<body>
<div style="width: 100%; margin: 0px;">
    <style>
        /* hide optional elements */
        div.exercises-header {
            display: none;
        }
        div#extras{
            display: none;
        }

        /* customize color scheme to match */
        article.exercises-content {
            background-color: transparent;
        }
        div#workarea {
            background-color: white;
            padding: 8px;
            margin-bottom: 8px;
        }
    </style>
    <header style="display: none;" />
    <div id="container" class="single-exercise visited-no-recolor"
            style="overflow: hidden;">
        <article class="exercises-content clearfix">
        <div class="exercises-header"><h2 class="section-headline">
                <div class="topic-exercise-badge">&nbsp;</div>
                <span class="practice-exercise-topic-context">Practicing</span>
        </h2></div>
        <div class="exercises-body">
            <div class="exercises-stack">&nbsp;</div>
            <div class="exercises-card current-card">
                <div class="current-card-container card-type-problem">
                    <div class="current-card-container-inner vertical-shadow">
                        <div class="current-card-contents">
                        </div>
                    </div>
                    <div id="extras" class="single-exercise">
                        <ul>
                            <li>
                                <a id="scratchpad-show" href style>
                                    Show scratchpad</a>
                                <span id="scratchpad-not-available"
                                        style="display: none;">
                                    Scratchpad not available</span>
                            </li>
                            <li class="debug-mode">
                                <a href="?debug">Debug mode</a>
                            </li>
                            <li>
                                <a id="problem-permalink" href>
                                    Problem permalink</a>
                            </li>
                        </ul>
                    </div>
                </div>
            </div>
        </div>
        </article>
    </div>
    <footer id="footer" class="short" style="display: none;"></footer>
</div>
</body>
</html>""")


class KhanExerciseTag(tags.BaseTag):
    """Custom tag for embedding Khan Academy Exercises."""

    @classmethod
    def name(cls):
        return 'Khan Exercise'

    def render(self, node):
        """Embed just a <script> tag that will in turn create an <iframe>."""
        name = node.attrib.get('name')
        caption = name.replace('_', ' ')
        return cElementTree.XML(
            """
<div style='width: 450px;'>
  Khan Academy Exercise: %s
  <script src="%s" type="text/javascript"></script>
</div>""" % (
    cgi.escape(caption),
    URL_BASE + '/khan-exercises/embed.js?static:%s' % name))

    def get_schema(self, unused_handler):
        """Make schema with a list of all exercises by inspecting zip file."""
        zip_file = zipfile.ZipFile(ZIP_FILE)
        exercise_list = []
        for name in zip_file.namelist():
            if name.startswith(EXERCISE_BASE) and name != EXERCISE_BASE:
                exercise_list.append(name[len(EXERCISE_BASE):])
        items = []
        index = 1
        for url in sorted(exercise_list):
            name = url.replace('.html', '')
            caption = name.replace('_', ' ')
            items.append((name, '#%s: %s' % (index, caption)))
            index += 1

        reg = schema_fields.FieldRegistry('Khan Exercises')
        reg.add_property(
            schema_fields.SchemaField(
                'name', 'Exercises', 'select', optional=True,
                select_data=items,
                description=('The relative URL name of the exercise.')))
        return reg


class KhanExerciseRenderer(utils.BaseHandler):
    """A handler that renders Khan Academy Exercise."""

    def _render_indirect(self, slug):
        parts = slug.split(':')
        if len(parts) != 2:
            raise Exception(
                'Error processing request. Expected \'ity_ef_slug\' in a form '
                'of \'protocol:identifier\'.')

        if 'static' != parts[0]:
            raise Exception('Bad protocol.')

        zip_file = zipfile.ZipFile(ZIP_FILE)
        html_file = zip_file.open(EXERCISE_BASE + parts[1] + '.html')
        self.response.write(html_file.read())

    def _find_ns_from_context_path(self, context_path):
        """Finds a course for a given context_path."""
        if not context_path:
            return None
        for course in sites.get_all_courses():
            if course.slug == context_path:
                return course
        return None

    def _record_student_submission(self, context_path, data):
        """Record data in a specific course namespace."""
        ns = appengine_config.DEFAULT_NAMESPACE_NAME
        course = self._find_ns_from_context_path(context_path)
        if course:
            ns = course.namespace

        original_ns = namespace_manager.get_namespace()
        namespace_manager.set_namespace(ns)
        try:
            models.EventEntity.record(
                'module-khanex.exercise-submit', self.get_user(), data)
        finally:
            namespace_manager.set_namespace(original_ns)

    def _get_origin_context_path(self, data):
        """Extract lesson context path from the exercise data submission."""

        # we need to determine what course context_path this submission is for;
        # to do so we first look at the 'location' of the page showing the
        # exercise, inside of it we look at the 'ity_ef_origin' showing the
        # location of the page the exercise was embedded into; from the page
        # address we extract the context path and locate the course mapped
        # to it; this is UGLY, but I don't have a better way to do it now
        json = transforms.loads(data)
        if json:
            location = json.get('location')
            if location:
                location = urllib2.unquote(location)
                params_map = urlparse.parse_qs(location)
                ity_ef_origin = params_map.get('ity_ef_origin')
                if ity_ef_origin:
                    ity_ef_origin = ity_ef_origin[0]
                    origin_path = urlparse.urlparse(ity_ef_origin)
                    if origin_path.path:
                        parts = origin_path.path.split('/')
                        # we may have no context_path: '/unit?...'
                        if len(parts) == 2 and parts[1] == 'unit':
                            return '/'
                        # we may have a context_path: '/course/unit?...'
                        if len(parts) == 3 and parts[2] == 'unit':
                            return '/' + parts[1]
                        raise Exception('Unknown URL path pattern: %s.' % parts)
        return None

    def post(self):
        """Handle POST, i.e. 'Check Answer' button is pressed."""
        data = self.request.get('ity_ef_audit')
        self._record_student_submission(
            self._get_origin_context_path(data), data)
        self.response.write('{}')  # we must return valid JSON

    def get(self):
        """Handle GET."""
        rule = self.request.get('ity_ef_rule')
        slug = self.request.get('ity_ef_slug')

        # render raw
        if rule == 'raw':
            self.response.write(EXERCISE_HTML_PAGE_RAW)
            return

        # render indirect
        if slug:
            self._render_indirect(slug)
            return

        self.error(404)


custom_module = None


def register_module():
    """Registers this module in the registry."""

    zip_handler = (URL_BASE + '/(.*)', sites.make_zip_handler(ZIP_FILE))
    namespaced_zip_handler = (
        '/khan-exercises/(.*)', sites.make_zip_handler(ZIP_FILE))
    render_handler = (
        URL_BASE + '/khan-exercises/khan-exercises/indirect/',
        KhanExerciseRenderer)

    global custom_module
    custom_module = custom_modules.Module(
        'Khan Academy Exercise',
        'A set of pages for delivering Khan Academy Exercises via '
        'Course Builder.',
        [render_handler, zip_handler], [namespaced_zip_handler])
    return custom_module
