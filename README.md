## Markdowndiff

This library provides diff capabilities for parsed markdown text.

# Installation    
You can either install from source or from a built wheel.
To install from source, use ```git clone``` and  ```pip install .``` in the root directory
To install from a prebuilt wheel file, use :
```wget https://github.com/AutoriteDeLaConcurrence/markdowndiff/dist/markdowndiff-0.0.1-py3-none-any.whl```
and ```pip install markdowndiff-0.0.1-py3-none-any.whl```

# Quick use    
Import the modules you will use from the package : 
	from markdowndiff import main, html_formatter

You can then diff markdown texts in the following way :
```
diff = main.diff_trees(left, right, diff_options=None, formatter=None):(
	leftTree,
	rightTree,
	diff_options,
	formatter=formatter
)
```
You need to provide the following arguments:
*	First and second positionnal arguments : the old and the new version of the tree. You will get better results by restrictring the diff to the ```<body>``` element.
*	```diff_options``` : Options to fine-tune the diffing process. ```F``` is between 0 and 1 and is the minimum similarity for nodes to be matched.
*	```formatter``` : Handles the way the result is displayed. ```html_formatter.HTMLFormatter.getDefault()``` is a good starting point

The result of diff_from_texts is a lxml tree. To get a standalone - and pretty - html result when the diff was computed on the html bodies, use :
```main.display_diff_html(diff, title, stylesheets)```
You will need to provide the document title, and stylesheets for markdown and diff content. See ```data``` directory for examples.

# Examples
Full code to compute the diff between to commits for a given file:
```
from markdowndiff import main, html_formatter
from git import Repo
import pandoc
import io
import lxml
import lxml.html

repo = Repo(r"path/to/repo")
assert not repo.bare

oldCOmmit = "oldCommitSha"
newCommit = "newCommitSha"
stylesheets = ["relative path to stylesheets to include"]
filepath = "path/to/the/file"

def getTree(repo, path, commitSha):
    commit = repo.commit(commitSha)
    output = io.BytesIO()
    commit.tree[path].stream_data(output)
    text = output.getvalue().decode("utf-8")
    parsedText = pandoc.read(text, format="gfm")
    html = pandoc.write(parsedText, format="html", options=["-s", "--eol=lf", "--sandbox"])
    return lxml.html.fromstring(html, parser=lxml.etree.HTMLParser())

oldTree = getTree(repo, filepath, oldCommit,)
oldTreeBody = oldTree.xpath("//body")[0]
newTree = getTree(repo, filepath, newCommit)
newTreeBody = newTree.xpath("//body")[0]

diff = main.diff_trees(
    oldTreeBody,
    newTreeBody,
    diff_options={"F": 0.5, "fast_match": True},
    formatter=html_formatter.HTMLFormatter.getDefault()
)
    
full_html = main.display_diff_html(diff, "Computed difference", stylesheets)
lxml.html.open_in_browser(full_html)
```

# Demo    
You can find a demonstration of this differ in action [here](https://autoritedelaconcurrence.github.io/markdowndiff-demo/)

# Contributions    
This repository builds on the implementation of ["Change Detection in Hierarchically Structured Information"](http://ilpubs.stanford.edu/115/1/1995-46.pdf) provided by [xmldiff](https://github.com/Shoobx/xmldiff).
