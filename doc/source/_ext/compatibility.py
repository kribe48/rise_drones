from docutils import nodes
from docutils.parsers.rst import Directive
from docutils.parsers.rst import directives
from docutils.statemachine import ViewList
from sphinx.util.nodes import nested_parse_with_titles

import os
import requests # to get image from the web
import shutil # to save it locally

level = ('-', 'implemented', 'verified')

targets = {
  'ardupilot': 'ArduPilot',
  'dji': 'DJI',
  'py-client': 'py--client',
  'crm': 'CRM'
}

colors = {
  '-': 'not_implemented-lightgrey',
  'implemented': 'implemented-blue',
  'verified': 'verified-brightgreen'
}

def CompatibilityChoices(argument):
  return directives.choice(argument, level)

class Compatibility(Directive):
  has_content = True
  required_arguments = 0
  optional_arguments = 0
  final_argument_whitespace = True

  option_spec = { target : CompatibilityChoices for target in targets }

  def run(self):
    self.assert_has_content()

    if not self.options:
      return []

    images = list()
    for key, value in self.options.items():
      images.append('.. image:: images/' + targets[key] + '-' + colors[value] + '.png')

    file = [
      '.. tabularcolumns:: ' + 'C' * len(self.options),
      '.. csv-table::',
      '',
      '  ' + ', '.join(images),
      ''
    ]

    rst = ViewList()
    linenr = 0
    for line in file:
      linenr += 1
      # Add the content one line at a time. Second argument is the
      # filename to report in any warnings or errors, third argument is
      # the line number.
      rst.append(line, "temp.rst", linenr)

    # Create a node.
    node = nodes.section()
    node.document = self.state.document

    # Parse the rst.
    nested_parse_with_titles(self.state, rst, node)

    # And return the result.
    return node.children


def download_images(filenames):
  for filename in filenames:
    if not os.path.isfile('source/images/' + filename):
      r = requests.get("https://raster.shields.io/badge/" + filename, stream=True)

      if r.status_code == 200:
        r.raw.decode_content = True

        with open('source/images/' + filename, 'wb') as f:
          shutil.copyfileobj(r.raw, f)
      else:
        print('Failed to download {}'.format(filename))


def setup(app):
  for _, target in targets.items():
    for _, color in colors.items():
      download_images([target + '-' + color + '.png'])

  app.add_directive("compatibility", Compatibility)
  return {'version': '0.1', 'parallel_read_safe': True, 'parallel_write_safe': True}
