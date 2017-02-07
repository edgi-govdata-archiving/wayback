A node application with the following capabilities:
* Take 2 URLs as input and visualize their differences
* Take a formatted URL and return raw JSON from pagefreezer
* Take a formatted URL and automatically display a diff

#####Usage:
install the node dependencies with `npm install`, then
run `node app.js`

######Manual view:
access the main view at `http://localhost:3000`

Screenshot:
![screenshot](screenshot.png)

######URL Schemes:
Aside from the basic interface, a GET request may be made to:
`http://localhost:3000/diff`

With parameters:
`old_url` (required),
`new_url` (required),
`as` (optional can be `json` or `view`)

######Example:
http://localhost:3000/diff?old_url=https://raw.githubusercontent.com/edgi-govdata-archiving/pagefreezer-cli/master/archives/truepos-major-changes-a.html&new_url=https://raw.githubusercontent.com/edgi-govdata-archiving/pagefreezer-cli/master/archives/truepos-major-changes-b.html&as=view
Automatically runs the diff and displays the output
