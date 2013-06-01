#
#    Khan Academy Exercises for Course Builder
#
#    Copy Right (C) 2013 Pavel Simakov (pavel@vokamis.com)
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

"""Khan Academy exercises for Course Builder.


This extension lets you host Khan Academy exercises in your Course Builder
course. These exercises make learning complex subjects fun and they are free to
everyone! However, the framework is very complex; it's difficult to embed its
exercises into another web site. We made framework changes, which make it
easier to embed the exercises and collect the exercise results right in your
Course Builder course.

Here is how to install, activate and use this module:
    - download Course Builder (1.4.1)
    - download this package
    - copy all files in this package into /modules/khanex/... folder of your
      Course Builder application folder
    - edit main.app of your application
        - add new import where all other modules are imported:
          import modules.khanex.khanex
        - enable the module, where all other modules are enabled:
          modules.khanex.khanex.register_module().enable()
    - restart your local development sever or re-deploy your application
    - edit a lesson using visual editor; you should be able to add a new
      component type "Khan Academy Exercise"
    - the component editor should show a list of all exercises available in a
      dropdown list; there should be over 400 exercises listed here
    - pick one exercise, save the component configuration
    - add empty exercise definition var activity = []; uncheck 'Activity Listed'
    - save  the lesson
    - enable gcb_can_persist_activity_events and gcb_can_persist_page_events
    - preview the lesson
    - click "Check Answer" and see how data is recorded in the datastore
      EventEntity table with a namespace appropriate for your course
    - this is it!

This work is based on my other project, which brings Khan Academy exercises to
WordPress. You can learn more about it here:
  http://www.softwaresecretweapons.com/jspwiki/khan-exercises

Here are the things I found difficult to do while completing this integration:
    - if a unit is marked completed in a progress tracking system, and author
      adds new unit - the progress indicator is now wrong and must be recomputed
      to account for a new added unit
    - why don't we circles next to the lessons of the left nav. of the unit?
    - how does a tag/module know what unit/lesson is being shown now? we need to
      pass some kind of course_context into tag/module... how much of view model
      do we expose to the tag/module? can a tag instance introspect what is
      above and below it in the rendering context?
    - we do show "Loading..." indicator while exercise JavaScript loads up,
      but it is dismissed too early now
    - tag.render() method must give access to the handler, ideally before the
      rendering phase begins
    - our model for tracking progress assumes lesson is an atomic thing; so
      if one has 3 exercises on one lesson page, only one marker is used and
      it is not possible to track progress of individual exercises; ideally any
      container should automatically support progress tracking for its children

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

from common import schema_fields
from common import tags
from controllers import sites
from controllers import utils
from models.config import ConfigProperty
from models.counters import PerfCounter
from models import custom_modules
from models import models
from models import transforms


ATTEMPT_COUNT = PerfCounter(
    'gcb-khanex-attempt-count',
    'A number of attempts made by all users on all exercises.')

WHITELISTED_EXERCISES = ConfigProperty(
    '_khanex_whitelisted', str, (
        'A white-listed exercises that can be show to students. If this list '
        'is empty, all exercises are available.'),
    default_value='', multiline=True)

ZIP_FILE = os.path.join(os.path.dirname(__file__), 'khan-exercises.zip')
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


def _allowed(name):
    """Checks if an exercise name is whitelisted for use."""
    return (
        not WHITELISTED_EXERCISES.value or
        name in WHITELISTED_EXERCISES.value)


class KhanExerciseTag(tags.BaseTag):
    """Custom tag for embedding Khan Academy Exercises."""

    @classmethod
    def name(cls):
        return 'Khan Academy Exercise'

    @classmethod
    def vendor(cls):
        return 'psimakov'

    def render(self, node):
        """Embed just a <script> tag that will in turn create an <iframe>."""
        name = node.attrib.get('name')
        caption = name.replace('_', ' ')
        return cElementTree.XML(
            """
<div style='width: 450px;'>
  Khan Academy Exercise: %s
  <br/>
  <script>
    // customize the style of the exercise iframe
    var ity_ef_style = "width: 750px;";
  </script>
  <script src="%s" type="text/javascript"></script>
</div>""" % (
    cgi.escape(caption), 'khan-exercises/embed.js?static:%s' % name))

    def get_schema(self, unused_handler):
        """Make schema with a list of all exercises by inspecting a zip file."""
        zip_file = zipfile.ZipFile(ZIP_FILE)
        exercise_list = []
        for name in zip_file.namelist():
            if name.startswith(EXERCISE_BASE) and name != EXERCISE_BASE:
                exercise_list.append(name[len(EXERCISE_BASE):])
        items = []
        index = 1
        for url in sorted(exercise_list):
            name = url.replace('.html', '')
            if _allowed(name):
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

    def _record_student_submission(self, data):
        """Record data in a specific course namespace."""
        # get student
        student = self.personalize_page_and_get_enrolled()
        if not student:
            return False

        # record submission
        models.EventEntity.record(
            'module-khanex.exercise-submit', self.get_user(), data)

        # update progress
        unit_id, lesson_id = self._get_unit_lesson_from(data)
        self.get_course().get_progress_tracker().put_activity_accessed(
            student, unit_id, lesson_id)

        return True

    def _get_unit_lesson_from(self, data):
        """Extract unit and lesson id from exercise data submission."""

        # we need to figure out unit and lesson id for the exercise;
        # we currently have no direct way of doing it, so we have to do it
        # indirectly == ugly...; an exercise captures a page URL where it was
        # embedded; we can parse that URL out and find all the interesting
        # parts from the query string

        unit_id = 0
        lesson_id = 0
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
                    if origin_path.query:
                        query = urlparse.parse_qs(origin_path.query)
                        unit_id = self._int_list_to_int(query.get('unit'))
                        lesson_id = self._int_list_to_int(query.get('lesson'))

                        # when we are on the first lesson of a unit, leson_id is
                        # not present :(; look it up
                        if not lesson_id:
                            lessons = self.get_course().get_lessons(unit_id)
                            if lessons:
                                lesson_id = lessons[0].lesson_id

        return unit_id, lesson_id

    def _int_list_to_int(self, list):
        if list:
            return int(list[0])
        return 0

    def post(self):
        """Handle POST, i.e. 'Check Answer' button is pressed."""
        data = self.request.get('ity_ef_audit')
        if self._record_student_submission(data):
            ATTEMPT_COUNT.inc()
            self.response.write('{}')  # we must return valid JSON on success
            return

        self.error(404)

    def get(self):
        """Handle GET."""
        rule = self.request.get('ity_ef_rule')
        slug = self.request.get('ity_ef_slug')

        # render raw
        if rule == 'raw':
            self.response.write(EXERCISE_HTML_PAGE_RAW)
            return

        # render indirect
        if slug and _allowed(slug):
            self._render_indirect(slug)
            return

        self.error(404)


custom_module = None


def register_module():
    """Registers this module in the registry."""

    # register custom tag
    tags.Registry.add_tag_binding('khanex', KhanExerciseTag)

    # register handlers
    zip_handler = (
        '/khan-exercises', sites.make_zip_handler(ZIP_FILE))
    render_handler = (
        '/khan-exercises/khan-exercises/indirect/', KhanExerciseRenderer)

    # register module
    global custom_module
    custom_module = custom_modules.Module(
        'Khan Academy Exercise',
        'A set of pages for delivering Khan Academy Exercises via '
        'Course Builder.',
        [], [render_handler, zip_handler])
    return custom_module
