from . import diff, formatting
import lxml


def diff_trees(left, right, diff_options={}, formatter=None):
    """Takes two lxml root elements or element trees"""
    if formatter is not None:
        formatter.prepare(left, right)
    differ = diff.Differ(**diff_options)
    diffs = differ.diff(left, right)

    if formatter is None:
        return list(diffs)

    return formatter.format(diffs, left)


def _getBaseHTML(title, cssFiles):
    stylesheets = ""
    for stylesheet in cssFiles:
        stylesheets += '<link rel="stylesheet" href="' + stylesheet + '">\n'

    return (
        """<html xmlns="http://www.w3.org/1999/xhtml" lang="" xml:lang="">
    <head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0, user-scalable=yes">
    <title>"""
        + title
        + """</title>\n"""
        + stylesheets
        + """
    </head>
    <body>
    </body>
    </html>"""
    )


def display_diff_html(diff, title, stylesheets):
    base_html = _getBaseHTML(title, stylesheets)
    new_file = lxml.html.fromstring(base_html, parser=lxml.etree.HTMLParser())
    default_body = new_file.xpath("//body")[0]
    default_body.getparent().replace(default_body, diff)
    return new_file
