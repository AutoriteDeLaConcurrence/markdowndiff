import re

from copy import deepcopy
from lxml import etree
from . import utils, diff_match_patch, placeholder


DIFF_NS = "http://namespaces.shoobx.com/diff"
DIFF_PREFIX = "diff"


# Flags for whitespace handling in the text aware formatters:
WS_BOTH = 3  # Normalize ignorable whitespace and text whitespace
WS_TEXT = 2  # Normalize whitespace only inside text tags
WS_TAGS = 1  # Delete ignorable whitespace (between tags)
WS_NONE = 0  # Preserve all whitespace


class BaseFormatter:
    def __init__(self, normalize=WS_TAGS, pretty_print=False):
        """Formatters must as a minimum have a normalize parameter

        This is used by the main API to decide is whitespace between the
        tags should be stripped (the remove_blank_text flag in lxml) and
        if tags that are known texts tags should be normalized before
        comparing. String content in non-text tags will not be
        normalized with the included formatters.

        pretty_print is used to choose between a compact and a pretty output.
        This is currently only used by the XML and HTML formatters.

        Formatters may of course have more options than these, but these
        two are the ones that can be set from the command-line.
        """

    def prepare(self, left_tree, right_tree):
        """Allows the formatter to prepare the trees before diffing

        That preparing may need some "unpreparing", but it's then done
        by the formatters format() method, and is not a part of the
        public interface."""

    def format(self, diff, orig_tree):
        """Formats the diff and returns a unicode string

        A formatter that returns XML with diff markup will need the original
        tree available to do it's job, so there is an orig_tree parameter,
        but it may be ignored by differs that don't need it.
        """


class XMLFormatter(BaseFormatter):
    """A formatter that also replaces formatting tags with unicode characters

    The idea of this differ is to replace structured content (in this case XML
    elements) with unicode characters which then participate in the regular
    text diffing algorithm. This is done in the prepare() step.

    Each identical XML element will get a unique unicode character. If the
    node is changed for any reason, a new unicode character is assigned to the
    node. This allows identity detection of structured content between the
    two text versions while still allowing customization during diffing time,
    such as marking a new formatting node. The latter feature allows for
    granular style change detection independently of text changes.

    In order for the algorithm to not go crazy and convert entire XML
    documents to text (though that is perfectly doable), a few rules have been
    defined.

    - The `textTags` attribute lists all the XML nodes by name which can
      contain text. All XML nodes within those text nodes are converted to
      unicode placeholders. If you want better control over which parts of
      your XML document are considered text, you can simply override the
      ``insert_placeholders(tree)`` function. It is purposefully kept small to
      allow easy subclassing.

    - By default, all tags inside text tags are treated as immutable
      units. That means the node itself including its entire sub-structure is
      assigned one unicode character.

    - The ``formattingTags`` attribute is used to specify tags that format the
      text. For these tags, the opening and closing tags receive unique
      unicode characters, allowing for sub-structure change detection and
      formatting changes. During the diff markup phase, formatting notes are
      annotated to mark them as inserted or deleted allowing for markup
      specific to those formatting changes.

    The diffed version of the structural tree is passed into the
    ``finalize(tree)`` method to convert all the placeholders back into
    structural content before formatting.

    The ``normalize`` parameter decides how to normalize whitespace.
    WS_TEXT normalizes only inside text_tags, WS_TAGS will remove ignorable
    whitespace between tags, WS_BOTH do both, and WS_NONE will preserve
    all whitespace.
    """

    def __init__(
        self, normalize=WS_NONE, pretty_print=True, text_tags=(), formatting_tags=()
    ):
        # Mapping from placeholders -> structural content and vice versa.
        self.normalize = normalize
        self.pretty_print = pretty_print
        self.text_tags = text_tags
        self.formatting_tags = formatting_tags
        self.placeholderer = placeholder.PlaceholderMaker(
            text_tags=text_tags, formatting_tags=formatting_tags
        )
        self.dmp = diff_match_patch.diff_match_patch()

    def prepare(self, left_tree, right_tree):
        """prepare() is run on the trees before diffing

        This is so the formatter can apply magic before diffing."""
        # We don't want to diff comments:
        self._remove_comments(left_tree)
        self._remove_comments(right_tree)

        self.placeholderer.do_tree(left_tree)
        self.placeholderer.do_tree(right_tree)

        etree.register_namespace(DIFF_PREFIX, DIFF_NS)
        etree.cleanup_namespaces(left_tree, top_nsmap={DIFF_PREFIX: DIFF_NS})
        etree.cleanup_namespaces(right_tree, top_nsmap={DIFF_PREFIX: DIFF_NS})

    def finalize(self, result_tree):
        """finalize() is run on the resulting tree before returning it

        This is so the formatter can apply magic after diffing."""
        self.placeholderer.undo_tree(result_tree)

    def format(self, diff, orig_tree):
        result = deepcopy(orig_tree)
        if isinstance(result, etree._ElementTree):
            root = result.getroot()
        else:
            root = result

        for action in diff:
            self.handle_action(action, root)

        self.finalize(root)

        etree.cleanup_namespaces(result, top_nsmap={DIFF_PREFIX: DIFF_NS})
        return self.render(result)

    def render(self, result):
        return etree.tounicode(result, pretty_print=self.pretty_print)

    def handle_action(self, action, result):
        action_type = type(action)
        method = getattr(self, "_handle_" + action_type.__name__)
        method(action, result)

    def _remove_comments(self, tree):
        comments = tree.xpath("//comment()")

        for element in comments:
            parent = element.getparent()
            if parent is None:
                # We can't remove top level comments, but they won't
                # be iterated over anyway, so we just skip them.
                continue
            parent.remove(element)

    def _xpath(self, node, xpath):
        # This method finds an element with xpath and makes sure that
        # one and exactly one element is found. This is to protect against
        # formatting a diff on the wrong tree, or against using ambiguous
        # edit script xpaths.
        if xpath[0] == "/":
            root = True
            xpath = xpath[1:]
        else:
            root = False

        if "/" in xpath:
            path, rest = xpath.split("/", 1)
        else:
            path = xpath
            rest = ""

        if "[" in path:
            path, index = path[:-1].split("[")
            index = int(index) - 1
            multiple = False
        else:
            index = 0
            multiple = True

        if root:
            path = "/" + path

        matches = []
        for match in node.xpath(path, namespaces=node.nsmap):
            # Skip nodes that have been deleted
            if self.placeholderer.DELETE_NAME not in match.attrib:
                matches.append(match)

        if index >= len(matches):
            raise ValueError(
                "xpath {}[{}] not found at {}.".format(
                    path, index + 1, utils.getpath(node)
                )
            )
        if len(matches) > 1 and multiple:
            raise ValueError(
                "Multiple nodes found for xpath {} at {}.".format(
                    path, utils.getpath(node)
                )
            )
        match = matches[index]
        if rest:
            return self._xpath(match, rest)
        return match

    def _extend_diff_attr(self, node, action, value):
        diffattr = f"{{{DIFF_NS}}}{action}-attr"
        oldvalue = node.attrib.get(diffattr, "")
        if oldvalue:
            value = oldvalue + ";" + value
        node.attrib[diffattr] = value

    def _delete_attrib(self, node, name):
        del node.attrib[name]
        self._extend_diff_attr(node, "delete", name)

    def _handle_DeleteAttrib(self, action, tree):
        node = self._xpath(tree, action.node)
        self._delete_attrib(node, action.name)

    def _delete_node(self, node):
        node.attrib[self.placeholderer.DELETE_NAME] = ""

    def _handle_DeleteNode(self, action, tree):
        node = self._xpath(tree, action.node)
        self._delete_node(node)

    def _insert_attrib(self, node, name, value):
        node.attrib[name] = value
        self._extend_diff_attr(node, "add", name)

    def _handle_InsertAttrib(self, action, tree):
        node = self._xpath(tree, action.node)
        self._insert_attrib(node, action.name, action.value)

    def _insert_node(self, target, node, position):
        node.attrib[self.placeholderer.INSERT_NAME] = ""
        target.insert(position, node)

    def _get_real_insert_position(self, target, position):
        # Find the real position:
        pos = 0
        offset = 0
        for child in target.getchildren():
            if self.placeholderer.DELETE_NAME in child.attrib:
                offset += 1
            else:
                pos += 1
            if pos > position:
                # We found the right offset
                break
        # Real position
        return position + offset

    def _handle_InsertNode(self, action, tree):
        # Insert node as a child. However, position is the position in the
        # new tree, and the diff tree may have deleted children, so we must
        # adjust the position for that.
        target = self._xpath(tree, action.target)
        position = self._get_real_insert_position(target, action.position)
        new_node = target.makeelement(action.tag, nsmap=target.nsmap)
        self._insert_node(target, new_node, position)

    def _handle_MoveNode(self, action, tree):
        node = self._xpath(tree, action.node)
        inserted = deepcopy(node)
        target = self._xpath(tree, action.target)
        self._delete_node(node)
        position = self._get_real_insert_position(target, action.position)
        self._insert_node(target, inserted, position)
        inserted.set(self.placeholderer.MOVE_NAME, "")
        node.set(self.placeholderer.MOVE_NAME, "")

    def _handle_RenameNode(self, action, tree):
        node = self._xpath(tree, action.node)
        node.attrib[self.placeholderer.RENAME_NAME] = node.tag
        node.tag = action.tag

    def _update_attrib(self, node, name, value):
        oldval = node.attrib[name]
        node.attrib[name] = value
        self._extend_diff_attr(node, "update", f"{name}:{oldval}")

    def _handle_UpdateAttrib(self, action, tree):
        node = self._xpath(tree, action.node)
        self._update_attrib(node, action.name, action.value)

    def _get_content_and_states(self, contentArray):
        # remove placeholders (except PH of single type) from array and remember the position of opening/closing placeholders
        result = []
        stateByIndex = {}
        currentState = {}
        open_close_map = {}

        for char in contentArray:
            if self.placeholderer.is_placeholder(char):
                entry = self.placeholderer.placeholder2tag[char]
                if entry.ttype == self.placeholderer.T_SINGLE:
                    result.append(char)
                elif entry.ttype == self.placeholderer.T_OPEN:
                    open_close_map[char] = entry.close_ph
                    open_close_map[entry.close_ph] = char
                    if char not in currentState:
                        currentState[char] = 0
                    currentState[char] += 1
                    stateByIndex[len(result)] = deepcopy(currentState)
                elif entry.ttype == self.placeholderer.T_CLOSE:
                    open_char = open_close_map[char]
                    currentState[open_char] -= 1
                    stateByIndex[len(result)] = deepcopy(currentState)
            else:
                result.append(char)
        return result, stateByIndex

    def _update_state(self, currentState, stateByIndex, index):
        #  update currentState with the (sparse) stateByIndex
        if index not in stateByIndex:
            return currentState
        else:
            newState = stateByIndex[
                index
            ]  # do not keep placeholders with level == 0, and forget nested level
            return set(filter(lambda key: newState[key] > 0, newState.keys()))

    def _merge_link_placeholders(  # TODO : create a placeholder map for merged placeholders
        self, commonPlaceholders, insertedPlaceholders, deletedPlaceholders
    ):
        def _is_link_element(ph):
            return self.placeholderer.placeholder2tag[ph].element.tag == "a"

        insertedLinks = list(filter(_is_link_element, insertedPlaceholders))
        if len(insertedLinks) == 0:
            return

        removedLinks = list(filter(_is_link_element, deletedPlaceholders))
        if len(removedLinks) == 0:
            return

        insertedLinkPH = insertedLinks.pop()
        removedLinkPH = removedLinks.pop()
        insertedPlaceholders.remove(insertedLinkPH)
        deletedPlaceholders.remove(removedLinkPH)

        newElement = etree.Element("a")
        oldHref = self.placeholderer.placeholder2tag[removedLinkPH].element.attrib[
            "href"
        ]
        newHref = self.placeholderer.placeholder2tag[insertedLinkPH].element.attrib[
            "href"
        ]
        if oldHref == newHref:
            commonPlaceholders.add(removedLinkPH)
        else:
            newElement.attrib[f"{{{DIFF_NS}}}" + "change-target"] = (
                oldHref + " -> " + newHref
            )

            (ph_open, ph_close) = self.placeholderer.get_both_placeholders(newElement)
            commonPlaceholders.add(ph_open)

    def _merge_states(self, leftState, rightState):
        commonPlaceholders = leftState & rightState
        insertedPlaceholders = rightState - leftState
        deletedPlaceholders = leftState - rightState

        self._merge_link_placeholders(
            commonPlaceholders, insertedPlaceholders, deletedPlaceholders
        )

        mergedState = commonPlaceholders
        mergedState.update(
            map(
                lambda ph: self.placeholderer.get_modified_ph(ph, "insert-formatting"),
                insertedPlaceholders,
            )
        )
        mergedState.update(
            map(
                lambda ph: self.placeholderer.get_modified_ph(ph, "delete-formatting"),
                deletedPlaceholders,
            )
        )
        return mergedState

    def _insert_spacing(self, tokenList):
        output = []
        pendingSpace = False

        for token in tokenList:
            if self.placeholderer.is_placeholder(token):
                if pendingSpace:
                    entry = self.placeholderer.placeholder2tag[token]
                    if entry.ttype == self.placeholderer.T_OPEN:
                        output.append(" ")
                        pendingSpace = False
            else:  # This is a word
                if pendingSpace:
                    output.append(" ")
                pendingSpace = True
            output.append(token)
        return output

    def _diff_rich_text(self, leftValueArray, rightValueArray):
        leftResult, leftStateByIndex = self._get_content_and_states(leftValueArray)
        rightResult, rightStateByIndex = self._get_content_and_states(rightValueArray)

        char1, char2, wordsArray = utils.diff_wordsToChars(leftResult, rightResult)
        diffMungedWords = self.dmp.diff_main(char1, char2)
        diffWords = utils.diff_charsToWords(diffMungedWords, wordsArray)

        stateByIndex = {}
        leftIndex = 0
        rightIndex = 0
        currentLeftState = set()
        currentRightState = set()
        stateByIndex = []

        for (
            op,
            _,
        ) in diffWords:  # create a list with the state of each token in the output
            if op == 0:  #  equal content
                currentLeftState = self._update_state(
                    currentLeftState, leftStateByIndex, leftIndex
                )
                currentRightState = self._update_state(
                    currentRightState, rightStateByIndex, rightIndex
                )
                commonState = self._merge_states(currentLeftState, currentRightState)
                stateByIndex.append(commonState)
                leftIndex += 1
                rightIndex += 1
            elif op == 1:  #  insertion
                currentRightState = self._update_state(
                    currentRightState, rightStateByIndex, rightIndex
                )
                state = deepcopy(currentRightState)
                state.add(self.placeholderer.diff_tags["insert"][0])
                stateByIndex.append(state)
                rightIndex += 1
            elif op == -1:  #  deletion
                currentLeftState = self._update_state(
                    currentLeftState, leftStateByIndex, leftIndex
                )
                state = deepcopy(currentLeftState)
                state.add(self.placeholderer.diff_tags["delete"][0])
                stateByIndex.append(state)
                leftIndex += 1

        oldState = set()
        splitOutput = []
        currentOpenedPH = []
        for i in range(
            0, len(stateByIndex)
        ):  # reinsert placeholders in the text, paying attention to the order of insertion
            newState = stateByIndex[i]
            openedPH = newState - oldState
            closedPH = oldState - newState
            phToReopen = set()
            while closedPH:
                last_ph_opened = currentOpenedPH.pop()
                entry = self.placeholderer.placeholder2tag[last_ph_opened]
                splitOutput.append(entry.close_ph)
                if last_ph_opened in closedPH:
                    closedPH.remove(last_ph_opened)
                else:
                    phToReopen.add(last_ph_opened)
            for ph in sorted(
                openedPH | phToReopen, reverse=True
            ):  # order tags to get more meaningful semantics
                currentOpenedPH.append(ph)
                splitOutput.append(ph)
            splitOutput.append(diffWords[i][1])  # append the text
            oldState = newState

        while currentOpenedPH:  # close tags still open at the end
            ph = currentOpenedPH.pop()
            entry = self.placeholderer.placeholder2tag[ph]
            splitOutput.append(entry.close_ph)

        return "".join(self._insert_spacing(splitOutput))

    def _make_diff_tags(self, left_value, right_value, node, update_tail=False):
        if bool(self.normalize & WS_TEXT):
            left_value = utils.cleanup_whitespace(left_value or "").strip()
            right_value = utils.cleanup_whitespace(right_value or "").strip()

        leftValueArray = utils.splitString(
            left_value or "", self.placeholderer.placeholder2tag.keys()
        )
        rightValueArray = utils.splitString(
            right_value or "", self.placeholderer.placeholder2tag.keys()
        )
        result = self._diff_rich_text(leftValueArray, rightValueArray)
        if update_tail:
            node.tail = result
        else:
            node.text = result

    def _handle_UpdateTextIn(self, action, tree):
        node = self._xpath(tree, action.node)
        if (
            self.placeholderer.INSERT_NAME in node.attrib
            and self.placeholderer.MOVE_NAME not in node.attrib
        ):
            # The whole node is already marked as inserted,
            # we don't need to diff-wrap the text.
            node.text = action.text
            return node
        left_value = node.text
        right_value = action.text
        node.text = None

        self._make_diff_tags(left_value, right_value, node, update_tail=False)
        return node

    def _handle_UpdateTextAfter(self, action, tree):
        node = self._xpath(tree, action.node)
        left_value = node.tail
        right_value = action.text
        node.tail = None
        parent = node.getparent()

        if (
            self.placeholderer.INSERT_NAME in parent.attrib
            and self.placeholderer.MOVE_NAME not in parent.attrib
        ):
            node.tail = action.text
            return node

        self._make_diff_tags(left_value, right_value, node, update_tail=True)
        return node
