import re
from operator import eq


def splitString(text, placeholderList=[]):
    # split text on spaces, punctuation and placeholder, and remove spaces.
    # TODO : simplify this function
    listCharsSplit = [";", "!", "?"]
    listCharsSplit.extend(placeholderList)

    output = []

    stringStart = 0
    for i in range(0, len(text)):
        if text[i] in listCharsSplit:
            if i > stringStart:
                output.append(text[stringStart:i])
            output.append(text[i])
            stringStart = i + 1
        if text[i] == " ":
            if i > stringStart:
                output.append(text[stringStart:i])
            stringStart = i + 1
    if stringStart < len(text):
        output.append(text[stringStart:])
    return output


def diff_wordsToChars(tokenList1, tokenList2):
    wordsArray = []
    wordsHash = {}
    wordsArray.append("")

    def diff_wordsToCharsMunge(tokens):
        chars = []
        for token in tokens:
            if token in wordsHash:
                chars.append(chr(wordsHash[token]))
            else:
                wordsArray.append(token)
                wordsHash[token] = len(wordsArray) - 1
                chars.append(chr(len(wordsArray) - 1))
        return "".join(chars)

    chars2 = diff_wordsToCharsMunge(tokenList2)
    chars1 = diff_wordsToCharsMunge(tokenList1)
    return (chars1, chars2, wordsArray)


def diff_charsToWords(diffs, lineArray):
    result = []
    for i in range(len(diffs)):
        for char in diffs[i][1]:
            word = lineArray[ord(char)]
            result.append((diffs[i][0], word))
    return result


def post_order_traverse(node):
    for child in node.getchildren():
        # PY3: Man, I want yield from!
        yield from post_order_traverse(child)
    yield node


def reverse_post_order_traverse(node):
    for child in reversed(node.getchildren()):
        # PY3: Man, I want yield from!
        yield from reverse_post_order_traverse(child)
    yield node


def breadth_first_traverse(node):
    # First yield the root node
    queue = [node]

    while queue:
        item = queue.pop(0)
        yield item
        queue.extend(item.getchildren())


# LCS from Myers: An O(ND) Difference Algorithm and Its Variations. This
# implementation uses Chris Marchetti's technique of only keeping the history
# per dpath, and not per node, so it should be vastly less memory intensive.
# It also skips any items that are equal in the beginning and end, speeding
# up the search, and using even less memory.
def longest_common_subsequence(left_sequence, right_sequence, eqfn=eq):

    start = 0
    lend = lslen = len(left_sequence)
    rend = rslen = len(right_sequence)

    # Trim off the matching items at the beginning
    while (
        start < lend
        and start < rend
        and eqfn(left_sequence[start], right_sequence[start])
    ):
        start += 1

    # trim off the matching items at the end
    while (
        start < lend
        and start < rend
        and eqfn(left_sequence[lend - 1], right_sequence[rend - 1])
    ):
        lend -= 1
        rend -= 1

    left = left_sequence[start:lend]
    right = right_sequence[start:rend]

    lmax = len(left)
    rmax = len(right)
    furthest = {1: (0, [])}

    if not lmax + rmax:
        # The sequences are equal
        r = range(lslen)
        return zip(r, r)

    for d in range(0, lmax + rmax + 1):
        for k in range(-d, d + 1, 2):
            if k == -d or (k != d and furthest[k - 1][0] < furthest[k + 1][0]):
                # Go down
                old_x, history = furthest[k + 1]
                x = old_x
            else:
                # Go left
                old_x, history = furthest[k - 1]
                x = old_x + 1

            # Copy the history
            history = history[:]
            y = x - k

            while x < lmax and y < rmax and eqfn(left[x], right[y]):
                # We found a match
                history.append((x + start, y + start))
                x += 1
                y += 1

            if x >= lmax and y >= rmax:
                # This is the best match
                return (
                    [(e, e) for e in range(start)]
                    + history
                    + list(zip(range(lend, lslen), range(rend, rslen)))
                )
            else:
                furthest[k] = (x, history)


WHITESPACE = re.compile("\\s+", flags=re.MULTILINE)


def cleanup_whitespace(text):
    return WHITESPACE.sub(" ", text)


def getpath(element, tree=None):
    if tree is None:
        tree = element.getroottree()
    xpath = tree.getpath(element)
    if xpath[-1] != "]":
        # The path is unique without specifying a count. However, we always
        # want that count, so we add [1].
        xpath = xpath + "[1]"
    return xpath
