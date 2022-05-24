import re

from collections import namedtuple
from copy import deepcopy
from lxml import etree

DIFF_NS = "http://namespaces.shoobx.com/diff"
DIFF_PREFIX = "diff"


# This is the start of the BMP(0) private use area.
# If you end up having more than 6400 different tags inside text tags
# this will bleed over to non private use area, but that's highly
# unlikely.
PLACEHOLDER_START = 0xE000

PlaceholderEntry = namedtuple("PlaceholderEntry", "element ttype close_ph")


class PlaceholderMaker:
    """Replace tags with unicode placeholders

    This class searches for certain tags in an XML tree and replaces them
    with unicode placeholders. The idea is to replace structured content
    (in this case XML elements) with unicode characters which then
    participate in the regular text diffing algorithm. This makes text
    diffing easier and faster.

    The code can then unreplace the unicode placeholders with the tags.
    """

    INSERT_NAME = "{%s}insert" % DIFF_NS
    DELETE_NAME = "{%s}delete" % DIFF_NS
    RENAME_NAME = "{%s}rename" % DIFF_NS
    MOVE_NAME = "{%s}move" % DIFF_NS

    # Placeholder tag type
    T_OPEN = 0
    T_CLOSE = 1
    T_SINGLE = 2

    def __init__(self, text_tags=(), formatting_tags=()):
        self.text_tags = text_tags
        self.formatting_tags = formatting_tags
        self.placeholder2tag = {}
        self.tag2placeholder = {}
        self.placeholder = PLACEHOLDER_START

        insert_elem = etree.Element(self.INSERT_NAME)
        insert_close = self.get_placeholder(insert_elem, self.T_CLOSE, None)
        insert_open = self.get_placeholder(insert_elem, self.T_OPEN, insert_close)

        delete_elem = etree.Element(self.DELETE_NAME)
        delete_close = self.get_placeholder(delete_elem, self.T_CLOSE, None)
        delete_open = self.get_placeholder(delete_elem, self.T_OPEN, delete_close)

        self.diff_tags = {
            "insert": (insert_open, insert_close),
            "delete": (delete_open, delete_close),
        }

    def get_both_placeholders(self, element):
        ph_close = self.get_placeholder(element, self.T_CLOSE, None)
        ph_open = self.get_placeholder(element, self.T_OPEN, ph_close)
        return (ph_open, ph_close)

    def get_placeholder(self, element, ttype, close_ph):
        tag = etree.canonicalize(element)
        ph = self.tag2placeholder.get((tag, ttype, close_ph))
        if ph is not None:
            return ph
        self.placeholder += 1
        ph = chr(self.placeholder)
        copy = deepcopy(element)
        copy.tail = None
        copy.text = None
        self.placeholder2tag[ph] = PlaceholderEntry(copy, ttype, close_ph)
        self.tag2placeholder[tag, ttype, close_ph] = ph
        return ph

    def get_modified_ph(self, ph, action):  ## TODO cache the results
        entry = self.placeholder2tag[ph]

        # Mark the tag as having a diff-action. We do need to
        # make a copy of it and get a new placeholder:
        elem = entry.element
        elem = deepcopy(elem)
        elem.attrib[f"{{{DIFF_NS}}}{action}"] = ""

        # And make a new placeholder for this new entry:
        if entry.ttype == self.T_SINGLE:
            ph_single = self.get_placeholder(elem, self.T_SINGLE, None)
            return ph_single

        ph_close = self.get_placeholder(elem, self.T_CLOSE, None)
        if entry.ttype == self.T_CLOSE:
            return ph_close

        ph_open = self.get_placeholder(elem, self.T_OPEN, ph_close)
        return ph_open

    def is_placeholder(self, char):
        return len(char) == 1 and char in self.placeholder2tag

    def is_formatting(self, element):
        return element.tag in self.formatting_tags

    def do_element(self, element):
        # Replace only formatting elements by text
        # if we have non formatting element followed by formatting elements, add formatting element into tail text

        previous_child = None

        for child in element:
            current_text = element.text or ""
            # Replace formatted nodes by text between two placeholders
            if self.is_formatting(child):
                self.do_element(child)
                tail = child.tail or ""
                if previous_child is not None:
                    current_text = previous_child.tail or ""
                (ph_open, ph_close) = self.get_both_placeholders(child)
                text = child.text or ""
                if previous_child is not None:
                    previous_child.tail = (
                        current_text + ph_open + text + ph_close + tail
                    )
                else:
                    element.text = current_text + ph_open + text + ph_close + tail
                # Remove the element from the tree now that we have inserted
                # replacement text. "remove" also deletes the tail text
                element.remove(child)
            else:
                # Start modifiying the tail of this child
                previous_child = child

    def do_tree(self, tree):
        if self.text_tags:
            for elem in reversed(tree.xpath("//" + "|//".join(self.text_tags))):
                self.do_element(elem)

    def split_string(self, text):
        regexp = "([%s])" % "".join(self.placeholder2tag)
        return re.split(regexp, text, flags=re.MULTILINE)

    def undo_string(self, text):
        result = etree.Element("wrap")
        element = None

        segments = self.split_string(text)
        while segments:
            seg = segments.pop(0)
            if not seg:
                continue

            # Segments can be either plain string or placeholders.
            if self.is_placeholder(seg):
                entry = self.placeholder2tag[seg]
                if entry.ttype == self.T_OPEN:
                    element = deepcopy(entry.element)
                    next_seg = segments.pop(0)
                    new_text = ""
                    nested = 0  # take into account nested tag of the same type.
                    while next_seg != entry.close_ph or nested != 0:
                        new_text += next_seg
                        if next_seg == seg:
                            nested += 1
                        elif next_seg == entry.close_ph:
                            nested -= 1
                        next_seg = segments.pop(0)
                    element.text = new_text or ""
                    self.undo_element(element)
                    result.append(element)
                elif entry.ttype == self.T_SINGLE:
                    # single element have no childs
                    element = deepcopy(entry.element)
                    result.append(element)
            else:
                if element is not None:
                    element.tail = element.tail or "" + seg
                else:
                    result.text = result.text or "" + seg
        return result

    def undo_element(self, elem):
        if self.placeholder2tag:
            if elem.text:
                index = 0
                content = self.undo_string(elem.text)

                if elem.text != content.text:
                    # Placeholders was replaced
                    elem.text = content.text
                    for child in content:
                        self.undo_element(child)
                        elem.insert(index, child)
                        index += 1

            for child in elem:
                self.undo_element(child)

            if elem.tail:
                content = self.undo_string(elem.tail)
                if elem.tail != content.text:
                    # Placeholders was replaced
                    elem.tail = content.text
                    parent = elem.getparent()
                    index = parent.index(elem) + 1
                    for child in content:
                        self.undo_element(child)
                        parent.insert(index, child)
                        index += 1

    def undo_tree(self, tree):
        self.undo_element(tree)


class HTMLPlaceholderMaker(PlaceholderMaker):
    def getDefault():
        return HTMLPlaceholderMaker(
            ["br", "hr"],
            ["strong", "b", "em", "i", "del", "ins", "sub", "sup", "u"],
            ["a"],
            ["p", "h1", "h2", "h3", "h4", "h5", "h6", "li", "td", "para"],
        )

    def __init__(
        self,
        single_formatting_tags=(),
        dual_formatting_tags=(),
        complex_formatting_tags=(),
        text_tags=(),
    ):
        all_formatting_tags = []
        all_formatting_tags.extend(list(single_formatting_tags))
        all_formatting_tags.extend(list(dual_formatting_tags))
        all_formatting_tags.extend(list(complex_formatting_tags))
        self.single_formatting_tags = single_formatting_tags
        self.dual_formatting_tags = dual_formatting_tags
        self.complex_formatting_tags = complex_formatting_tags
        super().__init__(formatting_tags=all_formatting_tags, text_tags=text_tags)

        for tag in self.dual_formatting_tags:  # create initial tags to ensure ordering
            elem = etree.Element(tag)
            self.get_both_placeholders(elem)

    def get_both_placeholders(self, element):
        if element.tag in self.single_formatting_tags:
            ph_single = self.get_placeholder(element, self.T_SINGLE, None)
            return (ph_single, "")
        elif element.tag in self.dual_formatting_tags:
            elem = etree.Element(element.tag)
            ph_close = self.get_placeholder(elem, self.T_CLOSE, None)
            ph_open = self.get_placeholder(elem, self.T_OPEN, ph_close)
            return (ph_open, ph_close)
        else:
            ph_close = self.get_placeholder(element, self.T_CLOSE, None)
            ph_open = self.get_placeholder(element, self.T_OPEN, ph_close)
            return (ph_open, ph_close)
