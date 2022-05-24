from copy import deepcopy
from difflib import SequenceMatcher
from lxml import etree
import re
from . import utils, actions, diff_match_patch


class Differ:
    def __init__(self, F=None, uniqueattrs=None, fast_match=False):
        # The minimum similarity between two nodes to consider them equal
        if F is None:
            F = 0.5
        self.F = F
        # uniqueattrs is a list of attributes or (tag, attribute) pairs
        # that uniquely identifies a node inside a document. Defaults
        # to 'xml:id'.
        if uniqueattrs is None:
            uniqueattrs = []
        self.uniqueattrs = uniqueattrs
        self.fast_match = fast_match

        # Avoid recreating this for every node
        self._sequencematcher = SequenceMatcher()
        self._sequence_ratio = self._sequencematcher.ratio
        self.clear()
        self.dmp = diff_match_patch.diff_match_patch()
        self.wordRegex = re.compile('([ .;,!?"])')

    def clear(self):
        # Use None for all values, as markings that they aren't done yet.
        self.left = None
        self.right = None
        self._matches = None
        self._l2rmap = None
        self._r2lmap = None
        self._inorder = None
        # Well, except the text cache, it's used by the ratio tests,
        # so we set that to a dict so the tests work.
        self._text_cache = {}

    def set_trees(self, left, right):
        self.clear()

        # Make sure we were passed two lxml elements:
        if isinstance(left, etree._ElementTree):
            left = left.getroot()
        if isinstance(right, etree._ElementTree):
            right = right.getroot()

        if not (etree.iselement(left) and etree.iselement(right)):
            raise TypeError(
                "The 'left' and 'right' parameters must be " "lxml Elements."
            )

        # Left gets modified as a part of the diff, deepcopy it first.
        self.left = deepcopy(left)
        self.right = right

    def append_match(self, lnode, rnode):
        self._l2rmap[id(lnode)] = rnode
        self._r2lmap[id(rnode)] = lnode
        self._matches.append((lnode, rnode))

    def remove_match(self, lnode, rnode):
        del self._l2rmap[id(lnode)]
        del self._r2lmap[id(rnode)]
        self._matches.remove((lnode, rnode))

    def match(self, left=None, right=None):
        if left is not None or right is not None:
            self.set_trees(left, right)

        if self._matches is not None:
            # We already matched these sequences, use the cache
            return self._matches

        # Initialize the caches:
        self._matches = []
        self._l2rmap = {}
        self._r2lmap = {}
        self._inorder = set()
        self._text_cache = {}

        lnodes = list(utils.post_order_traverse(self.left))
        rnodes = list(utils.post_order_traverse(self.right))

        # Make sure the roots are matched, we do that by
        # removing them from the lists of nodes, so it can't match, and add
        # them back last.
        lnodes.remove(self.left)
        rnodes.remove(self.right)

        if self.fast_match:
            # First find matches with longest_common_subsequence:
            matches = list(
                utils.longest_common_subsequence(
                    lnodes, rnodes, lambda x, y: self.node_ratio(x, y) >= self.F
                )
            )

            # Add the matches :
            for left_match, right_match in matches:
                self.append_match(lnodes[left_match], rnodes[right_match])

            # Then remove the nodes (needs to be done backwards):
            for left_match, right_match in reversed(matches):
                lnode = lnodes.pop(left_match)
                rnode = rnodes.pop(right_match)

        for lnode in lnodes:
            max_match = 0
            match_node = None

            for rnode in rnodes:  # TODO create an iterator that first try to match close to latest match
                match = self.node_ratio(lnode, rnode)
                if match > max_match:
                    match_node = rnode
                    max_match = match

                if match == 1.0:
                    # This is a total match, break here
                    break

            if max_match >= self.F:
                self.append_match(lnode, match_node)

                # We don't want to check nodes that already are matched
                if match_node is not None:
                    rnodes.remove(match_node)

        # post process match, iterate on tree top down and try to match children of matched nodes together.
        for rnode in utils.breadth_first_traverse(self.right):
            if id(rnode) in self._r2lmap and rnode.getchildren():
                lnode = self._r2lmap[id(rnode)]
                lchilds = lnode.getchildren()
                rchilds = rnode.getchildren()
                # remove childs that are already matched to a child of the match, copy list to avoid iterator invalidation when removing
                for rchild in list(rchilds):
                    if (
                        id(rchild) in self._r2lmap
                        and self._r2lmap[id(rchild)] in lchilds
                    ):
                        lchilds.remove(self._r2lmap[id(rchild)])
                        rchilds.remove(rchild)
                # now we can match the remaining childs together
                for rchild in rchilds:
                    max_match = 0
                    match_node = None
                    for lchild in lchilds:
                        match = self.node_ratio(lchild, rchild)
                        if match > max_match:
                            match_node = lchild
                            max_match = match
                        if match == 1.0:
                            break
                    if max_match >= self.F:
                        # remove old matches
                        if id(rchild) in self._r2lmap:
                            self.remove_match(self._r2lmap[id(rchild)], rchild)
                        if id(match_node) in self._l2rmap:
                            self.remove_match(match_node, self._l2rmap[id(match_node)])

                        # add new match
                        self.append_match(match_node, rchild)

        # Match the roots
        self.append_match(self.left, self.right)
        return self._matches

    def node_ratio(self, left, right):
        for attr in self.uniqueattrs:
            if not isinstance(attr, str):
                # If it's actually a sequence of (tag, attr), the tags must
                # match first.
                tag, attr = attr
                if tag != left.tag or tag != right.tag:
                    continue
            if attr in left.attrib or attr in right.attrib:
                # One of the nodes have a unique attribute, we check only that.
                # If only one node has it, it means they are not the same.
                return int(left.attrib.get(attr) == right.attrib.get(attr))

        (leaf_weight, match) = self.leaf_ratio(left, right)
        (child_weight, child_ratio) = self.child_ratio(left, right)

        if child_ratio is not None:
            match = (leaf_weight * match + child_weight * child_ratio) / (
                leaf_weight + child_weight
            )
        return match

    def node_text(self, node):
        if node in self._text_cache:
            return self._text_cache[node]
        # Get the texts and the tag as a start
        texts = node.xpath("text()")

        # Finally make one string, useful to see how similar two nodes are
        text = " ".join(texts).strip()
        result = utils.cleanup_whitespace(text)
        self._text_cache[node] = result
        return result

    def node_weight(self, node):
        return 1 + len(self.node_text(node))  # add 1 to account for the node itself

    def node_attribs(self, node):
        """Return a dict of attributes to consider for this node."""
        return node.attrib

    def leaf_ratio(self, left, right):
        # How similar two nodes are, with no consideration of their children
        # We use the word diff here. This is slightly faster than character diff.
        ltext = self.node_text(left)
        rtext = self.node_text(right)

        if len(ltext) == 0 and len(rtext) == 0:
            if left.tag == right.tag:
                return (1, 1)
            else:
                return (0, 0)
        if len(ltext) == 0 or len(rtext) == 0:
            return (max(len(ltext), len(rtext)), 0)

        tokenListLeft = utils.splitString(ltext)
        tokenListRight = utils.splitString(rtext)

        char1, char2, wa = utils.diff_wordsToChars(tokenListLeft, tokenListRight)

        diff = self.dmp.diff_main(char1, char2)
        total_weight = max(
            len(char1), len(char2)
        )  # this is the upper bound for the levensthein distance

        return (
            max(len(rtext), len(ltext)),
            1 - self.dmp.diff_levenshtein(diff) / total_weight,
        )

    def child_ratio(self, left, right):
        # How similar the children of two nodes are
        left_children = left.getchildren()
        right_children = right.getchildren()
        if not left_children and not right_children:
            return (0, None)
        total_weight = 0
        for child in left_children:
            total_weight += self.node_weight(child)
        for child in right_children:
            total_weight += self.node_weight(child)

        equal_weight = 0
        for lchild in left_children:
            for (
                rchild
            ) in right_children:  # TODO : find a better way to do this (getparent() ?)
                if self._l2rmap.get(id(lchild)) is rchild:
                    equal_weight += self.node_weight(lchild) + self.node_weight(rchild)
                    right_children.remove(rchild)
                    break

        return (total_weight / 2, equal_weight / total_weight)

    def update_node_tag(self, left, right):
        if left.tag != right.tag:
            left_xpath = utils.getpath(left)
            yield actions.RenameNode(left_xpath, right.tag)
            left.tag = right.tag

    def update_node_attr(self, left, right):
        left_xpath = utils.getpath(left)

        # Update: Look for differences in attributes

        left_keys = set(self.node_attribs(left).keys())
        right_keys = set(self.node_attribs(right).keys())
        new_keys = right_keys.difference(left_keys)
        removed_keys = left_keys.difference(right_keys)
        common_keys = left_keys.intersection(right_keys)

        # We sort the attributes to get a consistent order in the edit script.
        # That's only so we can do testing in a reasonable way...
        for key in sorted(common_keys):
            if left.attrib[key] != right.attrib[key]:
                yield actions.UpdateAttrib(left_xpath, key, right.attrib[key])
                left.attrib[key] = right.attrib[key]

        # Align: Not needed here, we don't care about the order of
        # attributes.

        # Insert: Find new attributes
        for key in sorted(new_keys):
            yield actions.InsertAttrib(left_xpath, key, right.attrib[key])
            left.attrib[key] = right.attrib[key]

        # Delete: remove removed attributes
        for key in sorted(removed_keys):
            if key not in left.attrib:
                # This was already moved
                continue
            yield actions.DeleteAttrib(left_xpath, key)
            del left.attrib[key]

    def update_node_text(self, left, right):
        left_xpath = utils.getpath(left)

        if left.text != right.text:
            yield actions.UpdateTextIn(left_xpath, right.text)
            left.text = right.text

        if left.tail != right.tail:
            yield actions.UpdateTextAfter(left_xpath, right.tail)
            left.tail = right.tail

    def find_pos(self, node):
        parent = node.getparent()
        # The paper here first checks if the child is the first child in
        # order, but I am entirely unable to actually make that happen, and
        # if it does, the "else:" will catch that case anyway, and it also
        # deals with the case of no child being in order.

        # Find the last sibling before the child that is in order
        i = parent.index(node)
        while i >= 1:
            i -= 1
            sibling = parent[i]
            if sibling in self._inorder:
                # That's it
                break
        else:
            # No previous sibling in order.
            return 0

        # Now find the partner of this in the left tree
        sibling_match = self._r2lmap[id(sibling)]
        node_match = self._r2lmap.get(id(node))

        i = 0
        for child in sibling_match.getparent().getchildren():
            if child is node_match:
                # Don't count the node we're looking for.
                continue
            if child in self._inorder or child not in self._l2rmap:
                # Count nodes that are in order, or will be deleted:
                i += 1
            if child is sibling_match:
                # We found the position!
                break
        return i

    def align_children(self, left, right):
        lchildren = [
            c
            for c in left.getchildren()
            if (id(c) in self._l2rmap and self._l2rmap[id(c)].getparent() is right)
        ]
        rchildren = [
            c
            for c in right.getchildren()
            if (id(c) in self._r2lmap and self._r2lmap[id(c)].getparent() is left)
        ]
        if not lchildren or not rchildren:
            # Nothing to align
            return

        lcs = utils.longest_common_subsequence(
            lchildren, rchildren, lambda x, y: self._l2rmap[id(x)] is y
        )

        for x, y in lcs:
            # Mark these as in order
            self._inorder.add(lchildren[x])
            self._inorder.add(rchildren[y])

        # Go over those children that are not in order:
        for lchild in lchildren:
            if lchild in self._inorder:
                # Already aligned
                continue

            rchild = self._l2rmap[id(lchild)]
            right_pos = self.find_pos(rchild)
            rtarget = rchild.getparent()
            ltarget = self._r2lmap[id(rtarget)]
            yield actions.MoveNode(
                utils.getpath(lchild), utils.getpath(ltarget), right_pos
            )
            # Do the actual move:
            left.remove(lchild)
            ltarget.insert(right_pos, lchild)
            # Mark the nodes as in order
            self._inorder.add(lchild)
            self._inorder.add(rchild)

    def diff(self, left=None, right=None):
        # Make sure the matching is done first, diff() needs the l2r/r2l maps.
        if not self._matches:
            self.match(left, right)

        # The paper talks about the five phases, and then does four of them
        # in one phase, in a different order that described. This
        # implementation in turn differs in order yet again.
        ltree = self.left.getroottree()

        for rnode in utils.breadth_first_traverse(self.right):
            # (a)
            rparent = rnode.getparent()
            ltarget = self._r2lmap.get(id(rparent))

            # (b) Insert
            if id(rnode) not in self._r2lmap:
                # (i)
                pos = self.find_pos(rnode)

                # (ii)

                yield actions.InsertNode(  # utils.getpath(ltarget, ltree)
                    utils.getpath(ltarget, ltree), rnode.tag, pos
                )
                lnode = ltarget.makeelement(rnode.tag)

                # (iii)
                self.append_match(lnode, rnode)
                ltarget.insert(pos, lnode)
                self._inorder.add(lnode)
                self._inorder.add(rnode)
                # And then we update attributes. This is different from the
                # paper, because the paper assumes nodes only has labels and
                # values. Nodes also has texts, we do them later.
                yield from self.update_node_attr(lnode, rnode)

            # (c)
            else:
                # Normally there is a check that rnode isn't a root,
                # but that's perhaps only because comparing valueless
                # roots is pointless, but in an elementtree we have no such
                # thing as a valueless root anyway.
                # (i)
                lnode = self._r2lmap[id(rnode)]

                # (iii) Move
                lparent = lnode.getparent()
                if ltarget is not lparent:
                    pos = self.find_pos(rnode)
                    yield actions.MoveNode(
                        utils.getpath(lnode, ltree), utils.getpath(ltarget, ltree), pos
                    )
                    # Move the node from current parent to target
                    lparent.remove(lnode)
                    ltarget.insert(pos, lnode)
                    self._inorder.add(lnode)
                    self._inorder.add(rnode)

                # Rename
                yield from self.update_node_tag(lnode, rnode)

                # (ii) Update
                # XXX If they are exactly equal, we can skip this,
                # maybe store match results in a cache?
                yield from self.update_node_attr(lnode, rnode)

            # (d) Align
            yield from self.align_children(lnode, rnode)

            # And lastly, we update all node texts. We do this after
            # aligning children, because when you generate an XML diff
            # from this, that XML diff update generates more children,
            # confusing later inserts or deletes.
            lnode = self._r2lmap[id(rnode)]
            yield from self.update_node_text(lnode, rnode)

        for lnode in utils.reverse_post_order_traverse(self.left):
            if id(lnode) not in self._l2rmap:
                # No match
                yield actions.DeleteNode(utils.getpath(lnode, ltree))
                lnode.getparent().remove(lnode)
