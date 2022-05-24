from . import formatting, placeholder
from copy import deepcopy
from lxml import etree
import lxml


class HTMLFormatter(formatting.XMLFormatter):
    def __init__(
        self,
        normalize=formatting.WS_NONE,
        pretty_print=True,
        text_tags=(),
        single_formatting_tags=(),
        dual_formatting_tags=(),
        complex_formatting_tags=(),
    ):

        super().__init__(normalize, pretty_print=pretty_print, text_tags=text_tags)

        self.dual_formatting_tags = dual_formatting_tags
        self.complex_formatting_tags = complex_formatting_tags
        self.text_tags = self.text_tags

        self.placeholderer = placeholder.HTMLPlaceholderMaker(
            single_formatting_tags=single_formatting_tags,
            dual_formatting_tags=dual_formatting_tags,
            complex_formatting_tags=complex_formatting_tags,
            text_tags=text_tags,
        )

    def getDefault():
        return HTMLFormatter(
            text_tags=("p", "h1", "h2", "h3", "h4", "h5", "h6", "li", "td", "para"),
            dual_formatting_tags=(
                "b",
                "u",
                "i",
                "strike",
                "em",
                "super",
                "sup",
                "sub",
                "span",
                "strong",
            ),
            single_formatting_tags=("br", "hr"),
            complex_formatting_tags=("a", "link"),
            normalize=formatting.WS_BOTH,
            pretty_print=True,
        )

    def addClass(self, element, className):
        if "class" in element.attrib:
            element.set("class", element.get("class") + " " + className)
        else:
            element.set("class", className)

    def modifyElement(self, element, state):
        prefix = "{%s}" % "http://namespaces.shoobx.com/diff"
        state = deepcopy(state)

        if element.tag == prefix + "delete":
            element.tag = "delete"
        if element.tag == prefix + "insert":
            element.tag = "insert"

        if prefix + "move" in element.attrib:
            self.addClass(element, "diff-moved")

        if prefix + "rename" in element.attrib:
            self.addClass(element, "diff-renamed")
            self.addClass(element, "tooltipped")
            element.set(
                "aria-label", "Previous tag : " + element.get(prefix + "rename")
            )

        if prefix + "insert" in element.attrib:
            self.addClass(element, "diff-inserted")

        if prefix + "delete" in element.attrib:
            self.addClass(element, "diff-deleted")

        if prefix + "change-target" in element.attrib:
            self.addClass(element, "diff-target-changed")
            self.addClass(element, "tooltipped ")
            element.set(
                "aria-label", element.attrib[prefix + "change-target"],
            )

        if prefix + "insert-formatting" in element.attrib:
            if element.tag == "a":
                if "old-href" in state:
                    if state["old-href"] != element.get("href"):
                        self.addClass(element, "diff-target-changed")
                        self.addClass(element, "tooltipped ")
                        element.set(
                            "aria-label",
                            state["old-href"] + " -> " + element.get("href"),
                        )
                    else:
                        self.addClass(element, "diff-no-format-changed")
                    del state["old-href"]
                else:
                    state["new-href"] = element.get("href")
                    self.addClass(element, "diff-inserted-formatting")

            else:
                self.addClass(element, "diff-inserted-formatting")
                if element.tag == "br":
                    newElement = lxml.etree.Element("span")
                    newElement.set("class", "diff-inserted")
                    newElement.text = "↩"
                    element.addprevious(newElement)

        if prefix + "delete-formatting" in element.attrib:
            element.set("old-formatting", element.tag)
            oldTag = element.tag
            element.tag = "span"

            self.addClass(element, "tooltipped")
            element.set("aria-label", "Previous formatting : " + oldTag)

            if oldTag == "a":
                if "new-href" in state:
                    if state["new-href"] != element.get("href"):
                        self.addClass(element, "diff-target-changed")
                        self.addClass(element, "tooltipped ")
                        element.set(
                            "aria-label",
                            element.get("href") + " -> " + state["new-href"],
                        )
                    del state["new-href"]
                else:
                    state["old-href"] = element.get("href")
                    self.addClass(element, "diff-deleted-formatting")
            elif oldTag == "br":
                element.set("class", "diff-deleted")
                element.tag = "span"
                element.text = "↩"
            else:
                self.addClass(element, "diff-deleted-formatting")

        for child in element:
            self.modifyElement(child, state)

    def modifyTree(self, tree):
        self.modifyElement(tree, {})

    def cleanWhitespaceFormatting(self, tree):
        for child in tree:
            self.cleanWhitespaceFormatting(child)
            if (
                (
                    child.tag in self.dual_formatting_tags
                    or child.tag in self.complex_formatting_tags
                    or child.tag in self.text_tags
                )
                and not len(child) > 0
                and (not child.text or len(child.text.strip()) == 0)
            ):
                tree.remove(child)

    def render(self, result):
        self.cleanWhitespaceFormatting(result)
        self.modifyTree(result)
        return result
