import unittest

from lxml import etree
from markdowndiff import formatting, placeholder, html_formatter, utils

DIFF_NS = "http://namespaces.shoobx.com/diff"
DIFF_PREFIX = "diff"

START = '<document xmlns:diff="http://namespaces.shoobx.com/diff"><node'
END = "</node></document>"


class PlaceholderMakerTests(unittest.TestCase):
    def test_get_placeholder(self):
        replacer = placeholder.PlaceholderMaker()
        # Get a placeholder:
        ph = replacer.get_placeholder(etree.Element("tag"), replacer.T_OPEN, None)
        self.assertEqual(ph, "\ue005")
        # Do it again:
        ph = replacer.get_placeholder(etree.Element("tag"), replacer.T_OPEN, None)
        self.assertEqual(ph, "\ue005")
        # Get another one
        ph = replacer.get_placeholder(etree.Element("tag"), replacer.T_CLOSE, ph)
        self.assertEqual(ph, "\ue006")

    def test_do_element(self):
        replacer = placeholder.PlaceholderMaker(["p"], ["b"])

        # Formatting tags get replaced, and the content remains
        text = "<p>This is a tag with <b>formatted</b> text.</p>"
        element = etree.fromstring(text)
        replacer.do_element(element)

        self.assertEqual(
            etree.tounicode(element),
            "<p>This is a tag with \ue006formatted\ue005 text.</p>",
        )

        replacer.undo_element(element)
        self.assertEqual(etree.tounicode(element), text)

        # Non formatting tags do not get replaced
        text = "<p>This is a tag with <foo>formatted</foo> text.</p>"
        element = etree.fromstring(text)
        replacer.do_element(element)
        result = etree.tounicode(element)
        self.assertEqual(result, "<p>This is a tag with <foo>formatted</foo> text.</p>")

        # Single formatting tags still get two placeholders.
        text = "<p>This is a <b/> with <foo/> text.</p>"
        element = etree.fromstring(text)
        replacer.do_element(element)
        result = etree.tounicode(element)
        self.assertEqual(result, "<p>This is a \ue008\ue007 with <foo/> text.</p>")

    def test_do_undo_element(self):
        replacer = placeholder.PlaceholderMaker(["p"], ["b"])

        # Formatting tags get replaced, and the content remains
        text = "<p>This <is/> a <f>tag</f> with <b>formatted</b> text.</p>"
        element = etree.fromstring(text)
        replacer.do_element(element)

        self.assertEqual(element.text, "This ")

        replacer.undo_element(element)
        result = etree.tounicode(element)
        self.assertEqual(result, text)

    def test_do_undo_element_double_format(self):
        replacer = placeholder.PlaceholderMaker(["p"], ["b", "u"])

        # Formatting tags get replaced, and the content remains
        text = "<p>This is <u>doubly <b>formatted</b></u> text.</p>"
        element = etree.fromstring(text)
        replacer.do_element(element)

        self.assertEqual(
            element.text, "This is \ue008doubly \ue006formatted\ue005" "\ue007 text."
        )

        replacer.undo_element(element)
        result = etree.tounicode(element)
        self.assertEqual(result, text)

    def test_rml_bug(self):
        etree.register_namespace(formatting.DIFF_PREFIX, formatting.DIFF_NS)
        before_diff = """<document xmlns:diff="http://namespaces.shoobx.com/diff">
                          <section>
                            <para>
                              <ref>4</ref>.
                              <u><b>At Will Employment</b></u>
                              .\u201cText\u201d
                            </para>
                          </section>
                        </document>"""
        tree = etree.fromstring(before_diff)
        replacer = placeholder.PlaceholderMaker(
            text_tags=("para",), formatting_tags=("b", "u", "i",),
        )
        replacer.do_tree(tree)
        after_diff = """<document xmlns:diff="http://namespaces.shoobx.com/diff">
                          <section>
                            <para>
                              <insert><ref>4</ref></insert>.
                              \ue008\ue006At Will Employment\ue005\ue007
                              .\u201c<insert>New </insert>Text\u201d
                            </para>
                          </section>
                        </document>"""

        # The diff formatting will find some text to insert.
        delete_attrib = "{%s}delete-format" % formatting.DIFF_NS
        replacer.placeholder2tag["\ue008"].element.attrib[delete_attrib] = ""
        replacer.placeholder2tag["\ue005"].element.attrib[delete_attrib] = ""
        tree = etree.fromstring(after_diff)
        replacer.undo_tree(tree)
        result = etree.tounicode(tree)
        expected = """<document xmlns:diff="http://namespaces.shoobx.com/diff">
                          <section>
                            <para>
                              <insert><ref>4</ref></insert>.
                              <u diff:delete-format=""><b>At Will Employment</b></u>
                              .\u201c<insert>New </insert>Text\u201d
                            </para>
                          </section>
                        </document>"""
        self.assertEqual(result, expected)


class HTMLPlaceholderMakerTests(unittest.TestCase):
    def test_get_placeholder(self):
        replacer = placeholder.HTMLPlaceholderMaker.getDefault()
        # Get a placeholder:
        ph = replacer.get_placeholder(etree.Element("tag"), replacer.T_OPEN, None)
        self.assertEqual(ph, "\ue017")
        # Do it again:
        ph = replacer.get_placeholder(etree.Element("tag"), replacer.T_OPEN, None)
        self.assertEqual(ph, "\ue017")
        # Get another one
        ph = replacer.get_placeholder(etree.Element("tag"), replacer.T_CLOSE, ph)
        self.assertEqual(ph, "\ue018")

    def test_do_undo_element_double_format(self):
        replacer = placeholder.HTMLPlaceholderMaker.getDefault()

        # Formatting tags get replaced, and the content remains
        text = "<p>This is <b>doubly <b>formatted</b></b> text.</p>"
        element = etree.fromstring(text)
        replacer.do_element(element)

        self.assertEqual(
            element.text, "This is \ue008doubly \ue008formatted\ue007" "\ue007 text."
        )

        replacer.undo_element(element)
        result = etree.tounicode(element)
        self.assertEqual(result, text)

    def test_complex_case(self):
        replacer = placeholder.HTMLPlaceholderMaker.getDefault()
        # Formatting tags get replaced, and the content remains
        text = """<body>
          <div id="id">
            <p>
              A common prefix helps the matching a lot. This is some simple text demonstrating the features of the <b>human text
              differ</b>. This <u><em>feature</em></u> attempts to make changelog nice &amp; readable for
              humans. <br/>The human text differ uses sentences as its first order
              matching. Let's see.
            </p>
          </div>
        </body>"""

        element = etree.fromstring(text)
        replacer.do_tree(element)
        replaced_text = """<body>
          <div id="id">
            <p>
              A common prefix helps the matching a lot. This is some simple text demonstrating the features of the \ue008human text
              differ\ue007. This \ue016\ue00afeature\ue009\ue015 attempts to make changelog nice &amp; readable for
              humans. \ue017The human text differ uses sentences as its first order
              matching. Let's see.
            </p>
          </div>
        </body>"""

        self.assertEqual(etree.tounicode(element), replaced_text)
        replacer.undo_tree(element)
        result = etree.tounicode(element)
        self.assertEqual(result, text)

    def test_dual_formatting(self):
        replacer = placeholder.HTMLPlaceholderMaker.getDefault()
        text = """<p>begin text <b> bold text </b> tail <em>emphasis <u>and underline</u></em> and another <b>text in bold</b></p>"""
        replaced_text = """begin text \ue008 bold text \ue007 tail \ue00aemphasis \ue016and underline\ue015\ue009 and another \ue008text in bold\ue007"""
        tree = etree.fromstring(text)
        replacer.do_tree(tree)

        self.assertEqual(tree.text, replaced_text)
