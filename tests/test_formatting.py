import os
import unittest

from lxml import etree
from markdowndiff import formatting, main, actions, html_formatter

from .testing import generate_filebased_cases

START = '<document xmlns:diff="http://namespaces.shoobx.com/diff"><node'
END = "</node></document>"

DIFF_NS = "http://namespaces.shoobx.com/diff"
DIFF_PREFIX = "diff"

class XMLFormatTests(unittest.TestCase):
    def _format_test(self, left, action, expected):
        formatter = formatting.XMLFormatter(pretty_print=False)
        result = formatter.format([action], etree.fromstring(left))
        self.assertEqual(result, expected)

    def test_incorrect_xpaths(self):
        left = '<document><node a="v"/><node>Text</node></document>'
        expected = START + ' diff:delete-attr="a">Text' + END

        with self.assertRaises(ValueError):
            action = actions.DeleteAttrib("/document/node", "a")
            self._format_test(left, action, expected)

        with self.assertRaises(ValueError):
            action = actions.DeleteAttrib("/document/ummagumma", "a")
            self._format_test(left, action, expected)

    def test_del_attr(self):
        left = '<document><node a="v">Text</node></document>'
        action = actions.DeleteAttrib("/document/node", "a")
        expected = START + ' diff:delete-attr="a">Text' + END

        self._format_test(left, action, expected)

    def test_del_node(self):
        left = '<document><node attr="val">Text</node></document>'
        action = actions.DeleteNode("/document/node")
        expected = START + ' attr="val" diff:delete="">Text' + END

        self._format_test(left, action, expected)

    def test_del_text(self):
        left = '<document><node attr="val">Text</node></document>'
        action = actions.UpdateTextIn("/document/node", None)
        expected = START + ' attr="val"><diff:delete>Text</diff:delete>' + END

        self._format_test(left, action, expected)

    def test_insert_attr(self):
        left = "<document><node>We need more text</node></document>"
        action = actions.InsertAttrib("/document/node", "attr", "val")
        expected = START + ' attr="val" diff:add-attr="attr">' "We need more text" + END

        self._format_test(left, action, expected)

    def test_insert_node(self):
        left = "<document></document>"
        action = actions.InsertNode("/document", "node", 0)
        expected = START + ' diff:insert=""/></document>'

        self._format_test(left, action, expected)

    def test_move_node(self):
        # Move 1 down
        left = '<document><node id="1" /><node id="2" /></document>'
        action = actions.MoveNode("/document/node[1]", "/document", 1)
        expected = (
            START + ' id="1" diff:delete="" diff:move=""/><node id="2"/><node '
            'id="1" diff:insert="" diff:move=""/></document>'
        )

        self._format_test(left, action, expected)

        # Move 2 up (same result, different diff)
        left = '<document><node id="1" /><node id="2" /></document>'
        action = actions.MoveNode("/document/node[2]", "/document", 0)
        expected = (
            START + ' id="2" diff:insert="" diff:move=""/><node id="1"/><node '
            'id="2" diff:delete="" diff:move=""/></document>'
        )

        self._format_test(left, action, expected)

    def test_rename_node(self):
        left = "<document><node><para>Content</para>Tail</node></document>"
        action = actions.RenameNode("/document/node[1]/para[1]", "newtag")
        expected = START + '><newtag diff:rename="para">Content' "</newtag>Tail" + END

        self._format_test(left, action, expected)

    def test_update_attr(self):
        left = '<document><node attr="val"/></document>'
        action = actions.UpdateAttrib("/document/node", "attr", "newval")
        expected = START + ' attr="newval" diff:update-attr="attr:val"/>' "</document>"

        self._format_test(left, action, expected)

    def test_update_text_in(self):
        left = '<document><node attr="val"/></document>'
        action = actions.UpdateTextIn("/document/node", "Text")
        expected = START + ' attr="val"><diff:insert>Text</diff:insert>' + END

        self._format_test(left, action, expected)

        left = "<document><node>This is a bit of text, right" + END
        action = actions.UpdateTextIn("/document/node", "Also a bit of text, rick")
        expected = (
            START + "><diff:delete>This is</diff:delete> <diff:insert>"
            "Also</diff:insert> a bit of text, <diff:delete>right"
            "</diff:delete> <diff:insert>rick</diff:insert>" + END
        )
        self.maxDiff = None
        self._format_test(left, action, expected)

    def test_update_text_after_1(self):
        left = "<document><node/><node/></document>"
        action = actions.UpdateTextAfter("/document/node[1]", "Text")
        expected = START + "/><diff:insert>Text</diff:insert>" "<node/></document>"

        self._format_test(left, action, expected)

    def test_update_text_after_2(self):
        left = "<document><node/>This is a bit of text, right</document>"
        action = actions.UpdateTextAfter("/document/node", "Also a bit of text, rick")
        expected = (
            START + "/><diff:delete>This is</diff:delete>"
            " <diff:insert>Also</diff:insert> a bit of text, <diff:delete>"
            "right</diff:delete> <diff:insert>rick</diff:insert></document>"
        )

        self._format_test(left, action, expected)


class FormatterFileTests(unittest.TestCase):

    formatter = None  # Override this
    maxDiff = None

    def process(self, left, right):
        normalize = bool(getattr(self.formatter, "normalize", 1) & formatting.WS_TAGS)
        parser = etree.XMLParser(remove_blank_text=normalize)
        left_tree = etree.parse(left, parser)
        right_tree = etree.parse(right, parser)
        return main.diff_trees(
            left_tree,
            right_tree,
            diff_options={"uniqueattrs": ["id"]},
            formatter=self.formatter,
        )


# Also test the bits that handle text tags:


class XMLFormatterFileTests(FormatterFileTests):

    # We use a few tags for the placeholder tests.
    formatter = formatting.XMLFormatter(
        normalize=formatting.WS_BOTH,
        pretty_print=True,
        text_tags=("p", "h1", "h2", "h3", "h4", "h5", "h6", "li"),
        formatting_tags=(
            "b",
            "u",
            "i",
            "strike",
            "em",
            "super",
            "sup",
            "sub",
            "link",
            "a",
            "span",
            "br",
        ),
    )

class HTMLFormatterTests(unittest.TestCase):

    def get_html_formatted_diff(self, left_text, right_text):
        formatter = html_formatter.HTMLFormatter.getDefault()

        tree = etree.fromstring(left_text)
        formatter.placeholderer.do_tree(tree)
        text_before = tree.text

        tree2 = etree.fromstring(right_text)
        formatter.placeholderer.do_tree(tree2)
        text_after = tree2.text

        formatter._make_diff_tags(text_before, text_after, tree, False)
        formatter.placeholderer.undo_tree(tree)

        etree.register_namespace(DIFF_PREFIX, DIFF_NS)
        etree.cleanup_namespaces(tree, top_nsmap={DIFF_PREFIX: DIFF_NS})
        return etree.tounicode(tree)

    def test_diff_process(self):
        text = """<p>another <b> text in a lot of bold</b> and yet some more <b>bold</b></p>"""
        text2 = """<p>another text <b>in a lot</b> of bold and yet <b>some more bold</b></p>"""
        expected = """<p xmlns:diff="http://namespaces.shoobx.com/diff">another <b diff:delete-formatting="">text</b> <b>in a lot</b> <b diff:delete-formatting="">of bold</b> and yet <b diff:insert-formatting="">some more</b> <b>bold</b></p>"""

        result = self.get_html_formatted_diff(text, text2)
        self.assertEqual(result, expected)

    def test_edge_cases(self):
        text1 = """<p>**<strong>10.2 QUELLES DONNÉES SONT TRAITEES PAR FLOA ET CDISCOUNT ?</strong></p>"""
        text2 = """<p><strong><strong>10.2 QUELLES DONNÉES SONT TRAITEES PAR FLOA ET CDISCOUNT ?</strong></strong></p>"""
        expected = """<p xmlns:diff="http://namespaces.shoobx.com/diff"><diff:delete>**</diff:delete> <strong>10.2 QUELLES DONNÉES SONT TRAITEES PAR FLOA ET CDISCOUNT ?</strong></p>"""

        result = self.get_html_formatted_diff(text1, text2)
        self.assertEqual(result, expected)

        text3 = """<p><strong>Confidentiality: <strong>Any arbitration shall remain confidential.</strong></strong></p>"""
        text4 = """<p><strong>Confidentiality: Any arbitration shall remain confidential.</strong></p>"""
        expected2 = """<p><strong>Confidentiality: Any arbitration shall remain confidential.</strong></p>"""

        result2 = self.get_html_formatted_diff(text3, text4)
        self.assertEqual(result2, expected2)

    def test_tag_order(self):
        text1 = """<p><b><a>text</a></b></p>"""
        text2 = """<p><b><a>text</a></b></p>"""
        expected = """<p><a><b>text</b></a></p>"""   # a tag should start outside dual formatting tags

        result = self.get_html_formatted_diff(text1, text2)
        self.assertEqual(result, expected)

        text3 = """<p>some <a href="link">more <b>text</b></a> <b>here</b></p>"""
        text4 = """<p>some <a href="link"><b>text</b></a> <b>here</b></p>"""
        expected2 = """<p xmlns:diff="http://namespaces.shoobx.com/diff">some <a href="link"><diff:delete>more</diff:delete> <b>text</b></a> <b>here</b></p>"""   # a tag should start outside dual formatting tags

        result2 = self.get_html_formatted_diff(text3, text4)
        self.assertEqual(result2, expected2)

    def test_link_change(self):
        text = """<p><a href="link1">Link</a></p>"""
        text2 = """<p><a href="link2">Link</a></p>"""
        expected = """<p xmlns:diff="http://namespaces.shoobx.com/diff"><a diff:change-target="link1 -&gt; link2">Link</a></p>"""

        result = self.get_html_formatted_diff(text, text2)
        self.assertEqual(result, expected)


# Add tests that use placeholder replacement (ie HTML)
data_dir = os.path.join(os.path.dirname(__file__), "test_data")
generate_filebased_cases(data_dir, XMLFormatterFileTests, suffix="html")
